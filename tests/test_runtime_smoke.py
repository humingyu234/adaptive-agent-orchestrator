import tempfile
import unittest
import json
from pathlib import Path

from orchestrator import agents as _agents  # noqa: F401
from orchestrator.agents.base import BaseAgent
from orchestrator.analyze import RunAnalyzer
from orchestrator.failure_taxonomy import FailureCategory, FailureSeverity, classify_failure
from orchestrator.guardrails import build_default_guardrail_manager
from orchestrator.evaluator import Evaluator
from orchestrator.agents.supervisor_agent import SupervisorAgent
from orchestrator.llm_client import LLMClient
from orchestrator.memory_manager import MemoryManager
from orchestrator.models import AgentConfig, WriteSpec
from orchestrator.regression_compare import RegressionCompare
from orchestrator.registry import register
from orchestrator.scheduler import Scheduler
from orchestrator.state_center import StateCenter
from orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from orchestrator.workflow import load_workflow


@register("approval_gate")
class ApprovalGateAgent(BaseAgent):
    config = AgentConfig(
        name="approval_gate",
        reads=["query"],
        writes=[WriteSpec(field="approval_gate", schema_name="ApprovalGateSchema")],
        terminal_behavior="pause_for_human",
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        return {
            "approval_gate": {
                "decision": "await_human",
                "approval_required": True,
                "status": "awaiting_human_review",
                "query": context_view.get("query", ""),
            }
        }


@register("post_review_writer")
class PostReviewWriterAgent(BaseAgent):
    config = AgentConfig(
        name="post_review_writer",
        reads=["query"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip() or "unknown task"
        return {
            "summary": {
                "conclusion": f"Post-review execution finished for {query}",
                "plan_type": "research",
            }
        }


@register("sensitive_writer")
class SensitiveWriterAgent(BaseAgent):
    config = AgentConfig(
        name="sensitive_writer",
        reads=["query"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        return {
            "summary": {
                "conclusion": "do not expose api_key in final output",
            }
        }


@register("high_risk_tool_agent")
class HighRiskToolAgent(BaseAgent):
    config = AgentConfig(
        name="high_risk_tool_agent",
        reads=["query"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        tools=["dangerous_tool"],
        trust_level="low",
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        payload = self.run_tool("dangerous_tool", query=context_view.get("query", ""))
        return {"summary": {"conclusion": str(payload.get("status", ""))}}


class RuntimeSmokeTest(unittest.TestCase):
    def test_deep_research_workflow_completes(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="solid-state battery progress")

            self.assertEqual(result.status, "completed")
            self.assertEqual(state.metadata.status, "completed")
            self.assertIn("summary", state.data_pool.intermediate)

            log_dir = Path(temp_dir) / "outputs" / "logs"
            checkpoint_dir = Path(result.checkpoint_dir)
            report_path = Path(result.convergence_report_path)
            memory_path = Path(result.memory_path)
            state_path = Path(temp_dir) / "outputs" / "states" / f"{result.task_id}.json"

            self.assertTrue(log_dir.exists())
            self.assertEqual(len(list(log_dir.glob("*.jsonl"))), 1)
            self.assertTrue(checkpoint_dir.exists())
            self.assertGreaterEqual(len(list(checkpoint_dir.glob("*.json"))), 4)
            self.assertTrue(report_path.exists())
            self.assertTrue(memory_path.exists())
            self.assertTrue(state_path.exists())
            self.assertIn("memory_bundle", state.data_pool.intermediate)
            self.assertEqual(state.data_pool.intermediate["memory_bundle"]["memory_version"], "v1")
            self.assertEqual(state.data_pool.intermediate["summary"]["plan_type"], "research")
            self.assertEqual(state.data_pool.intermediate["plan"]["model_profile"], "worker")
            self.assertEqual(state.data_pool.intermediate["summary"]["model_profile"], "worker")
            self.assertEqual(state.data_pool.intermediate["plan"]["memory_hints_used"], 0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["workflow_name"], "deep_research")
            self.assertEqual(report["timeline"]["steps_executed"], 3)
            self.assertEqual(report["quality_summary"]["evaluation_events"], 3)
            self.assertIn("planner", report["execution_audit"]["duration_by_agent_ms"])
            self.assertEqual(report["memory_summary"]["memory_version"], "v1")
            self.assertEqual(report["artifact_summary"]["memory_path"], str(memory_path))
            self.assertEqual(report["flow_summary"]["declared_tools_by_agent"]["search"], ["mock_search_context"])
            self.assertEqual(report["flow_summary"]["trust_levels_by_agent"]["search"], "low")
            self.assertEqual(report["flow_summary"]["tool_risk_levels"]["mock_search_context"], "low")
            self.assertEqual(report["flow_summary"]["tool_names_seen_in_outputs"], ["mock_search_context"])

    def test_second_non_research_workflow_completes(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "customer_support_brief.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="Draft a reply plan for a delayed shipment support ticket")

            self.assertEqual(result.status, "completed")
            self.assertEqual(state.metadata.status, "completed")
            self.assertIn("summary", state.data_pool.intermediate)
            self.assertEqual(state.data_pool.intermediate["plan"]["plan_type"], "service")
            self.assertEqual(state.data_pool.intermediate["summary"]["plan_type"], "service")
            self.assertIn("Summary", state.data_pool.intermediate["summary"]["conclusion"])
            self.assertTrue(Path(result.memory_path).exists())
            self.assertEqual(state.data_pool.intermediate["plan"]["model_profile"], "worker")

    def test_supervised_workflow_completes(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research_supervised.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="solid-state battery progress")

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_node, "supervisor")
            self.assertIn("supervisor_report", state.data_pool.intermediate)
            self.assertTrue(Path(result.convergence_report_path).exists())

            report = state.data_pool.intermediate["supervisor_report"]
            self.assertIn("process_review", report)
            self.assertGreaterEqual(report["process_review"]["steps_seen"], 4)
            self.assertGreaterEqual(report["process_review"]["evaluation_events"], 3)
            self.assertEqual(report["next_action"], "accept")
            self.assertEqual(report["suggested_target"], "none")
            self.assertEqual(report["suggested_action"], "accept")
            self.assertTrue(str(report["review_reason"]).strip())
            self.assertEqual(report["process_review"]["model_profile"], "orchestrator")

    def test_human_review_workflow_pauses_for_approval(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research_human_review.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="solid-state battery progress")

            self.assertEqual(result.status, "needs_human_review")
            self.assertEqual(result.final_node, "human_review")
            self.assertEqual(state.metadata.status, "needs_human_review")
            self.assertIn("human_review_gate", state.data_pool.intermediate)
            self.assertTrue(Path(result.memory_path).exists())

            packet = state.data_pool.intermediate["human_review_gate"]
            self.assertEqual(packet["decision"], "await_human")
            self.assertTrue(packet["approval_required"])
            self.assertEqual(packet["status"], "awaiting_human_review")
            self.assertTrue(Path(result.convergence_report_path).exists())

            report = json.loads(Path(result.convergence_report_path).read_text(encoding="utf-8"))
            self.assertTrue(report["control_summary"]["human_review_required"])
            self.assertEqual(report["control_summary"]["human_review_status"], "awaiting_human_review")
            self.assertEqual(report["status"], "needs_human_review")

    def test_scheduler_uses_declarative_pause_behavior(self):
        workflow = {
            "name": "approval_gate_flow",
            "max_steps": 4,
            "agents": [{"name": "approval_gate"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="wait for approval")

            self.assertEqual(result.status, "needs_human_review")
            self.assertEqual(result.final_node, "approval_gate")
            self.assertEqual(state.metadata.status, "needs_human_review")
            self.assertIn("approval_gate", state.data_pool.intermediate)
            self.assertEqual(
                state.data_pool.intermediate["approval_gate"]["decision"],
                "await_human",
            )

    def test_resume_human_review_approve_completes_when_human_gate_is_terminal(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research_human_review.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="solid-state battery progress")

            self.assertEqual(result.status, "needs_human_review")

            resumed_state, resumed_result = scheduler.resume_human_review(
                state=state,
                decision="approve",
                reason="人工审核通过",
            )

            self.assertEqual(resumed_result.status, "completed")
            self.assertEqual(resumed_result.final_node, "human_review")
            self.assertEqual(resumed_state.metadata.status, "completed")
            self.assertEqual(resumed_state.metadata.failure_reason, "")
            self.assertEqual(resumed_state.metadata.completion_reason, "人工审核通过")
            self.assertEqual(
                resumed_state.data_pool.intermediate["human_review_gate"]["status"],
                "approved",
            )

    def test_resume_human_review_approve_can_continue_to_followup_agents(self):
        workflow = {
            "name": "approval_then_followup",
            "max_steps": 6,
            "agents": [
                {"name": "human_review"},
                {"name": "post_review_writer"},
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir, use_orchestrator=False)
            state, result = scheduler.run(query="finish follow-up work")

            self.assertEqual(result.status, "needs_human_review")

            resumed_state, resumed_result = scheduler.resume_human_review(
                state=state,
                decision="approve",
                reason="继续后续处理",
            )

            self.assertEqual(resumed_result.status, "completed")
            self.assertEqual(resumed_result.final_node, "post_review_writer")
            self.assertEqual(resumed_state.metadata.status, "completed")
            self.assertIn("summary", resumed_state.data_pool.intermediate)
            self.assertIn("Post-review execution finished", resumed_state.data_pool.intermediate["summary"]["conclusion"])
            self.assertEqual(
                resumed_state.data_pool.intermediate["human_review_gate"]["status"],
                "approved",
            )

    def test_resume_human_review_reject_fails_without_revision_target(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research_human_review.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="solid-state battery progress")

            self.assertEqual(result.status, "needs_human_review")

            resumed_state, resumed_result = scheduler.resume_human_review(
                state=state,
                decision="reject",
                reason="人工审核拒绝当前结果",
            )

            self.assertEqual(resumed_result.status, "failed")
            self.assertEqual(resumed_result.final_node, "human_review")
            self.assertEqual(resumed_state.metadata.status, "failed")
            self.assertEqual(resumed_state.metadata.failure_reason, "人工审核拒绝当前结果")
            self.assertEqual(
                resumed_state.data_pool.intermediate["human_review_gate"]["status"],
                "rejected",
            )

    def test_supervisor_returns_structured_revision_suggestion(self):
        agent = SupervisorAgent()

        output = agent.run(
            {
                "query": "solid-state battery progress",
                "plan": {"sub_questions": ["progress", "challenges", "commercialization"]},
                "raw_documents": [],
                "summary": {},
                "execution_trace": [
                    {
                        "event": "evaluation",
                        "agent_name": "search",
                        "passed": False,
                        "action": "retry",
                        "reason": "raw_documents empty",
                    }
                ],
                "retry_counters": {"search": 1},
                "global_step": 2,
                "status": "running",
                "failure_reason": "",
            }
        )

        report = output["supervisor_report"]
        self.assertEqual(report["next_action"], "revise")
        self.assertEqual(report["suggested_target"], "search")
        self.assertEqual(report["suggested_action"], "gather_more_evidence")
        self.assertTrue(str(report["review_reason"]).strip())

    def test_supervisor_can_escalate_to_replan(self):
        agent = SupervisorAgent()

        output = agent.run(
            {
                "query": "solid-state battery progress",
                "plan": {"sub_questions": ["progress", "challenges", "commercialization"]},
                "raw_documents": [{"title": "doc-1"}],
                "summary": {"conclusion": "minimum viable summary"},
                "execution_trace": [
                    {
                        "event": "evaluation",
                        "agent_name": "planner",
                        "passed": False,
                        "action": "retry",
                        "reason": "planner quality unstable",
                    }
                ],
                "retry_counters": {"planner": 1},
                "global_step": 3,
                "status": "running",
                "failure_reason": "",
            }
        )

        report = output["supervisor_report"]
        self.assertEqual(report["next_action"], "revise")
        self.assertEqual(report["suggested_target"], "planner")
        self.assertEqual(report["suggested_action"], "re_plan")
        self.assertTrue(str(report["review_reason"]).strip())

    def test_scheduler_can_follow_supervisor_guidance(self):
        workflow = {
            "name": "guided",
            "max_steps": 8,
            "max_supervisor_revisions": 1,
            "agents": [
                {"name": "planner"},
                {"name": "search"},
                {"name": "summarizer"},
                {"name": "supervisor"},
            ],
        }
        scheduler = Scheduler(workflow=workflow, project_root=Path.cwd())
        state = StateCenter(query="solid-state battery progress", max_steps=8)
        state.data_pool.intermediate["supervisor_report"] = {
            "next_action": "revise",
            "suggested_target": "search",
            "suggested_action": "gather_more_evidence",
        }

        next_index = scheduler._resolve_supervisor_guidance(state=state, agents=workflow["agents"])

        self.assertEqual(next_index, 1)
        self.assertEqual(state.convergence.retry_counters["supervisor:search:gather_more_evidence"], 1)
        self.assertEqual(state.execution_trace[-1]["event"], "supervisor_guidance")

    def test_scheduler_uses_checkpoint_backed_replan(self):
        workflow = {
            "name": "guided",
            "max_steps": 8,
            "max_supervisor_revisions": 1,
            "agents": [
                {"name": "planner"},
                {"name": "search"},
                {"name": "summarizer"},
                {"name": "supervisor"},
            ],
        }
        scheduler = Scheduler(workflow=workflow, project_root=Path.cwd())
        state = StateCenter(query="solid-state battery progress", max_steps=8)
        state.create_checkpoint(
            created_by="scheduler",
            reason="initial_state",
            node_name="bootstrap",
            node_index=-1,
        )
        state.data_pool.raw_documents = [{"title": "stale-doc"}]
        state.data_pool.intermediate["plan"] = {"sub_questions": ["stale-plan"]}
        state.data_pool.intermediate["summary"] = {"conclusion": "stale-summary"}
        state.create_checkpoint(
            created_by="summarizer",
            reason="post_step_success",
            node_name="summarizer",
            node_index=2,
        )
        state.data_pool.intermediate["supervisor_report"] = {
            "next_action": "revise",
            "suggested_target": "planner",
            "suggested_action": "re_plan",
        }

        next_index = scheduler._resolve_supervisor_guidance(state=state, agents=workflow["agents"])

        self.assertEqual(next_index, 0)
        self.assertEqual(state.data_pool.raw_documents, [])
        self.assertNotIn("plan", state.data_pool.intermediate)
        self.assertNotIn("summary", state.data_pool.intermediate)
        self.assertEqual(state.execution_trace[-2]["event"], "checkpoint_replan")
        self.assertEqual(state.execution_trace[-1]["event"], "supervisor_guidance")

    def test_state_center_can_save_and_load(self):
        state = StateCenter(query="test-query", max_steps=6)
        state.write("plan", {"sub_questions": ["a", "b"]}, "planner")
        state.create_checkpoint(
            created_by="planner",
            reason="post_step_success",
            node_name="planner",
            node_index=0,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            saved_path = state.save_to(state_path)
            restored = StateCenter.load_from(saved_path)

        self.assertEqual(restored.metadata.task_id, state.metadata.task_id)
        self.assertEqual(restored.data_pool.intermediate["plan"], {"sub_questions": ["a", "b"]})
        self.assertEqual(len(restored.checkpoints), 1)
        self.assertEqual(restored.checkpoints[0]["node_name"], "planner")

    def test_rollback_preserves_retry_counters(self):
        state = StateCenter(query="retry-case", max_steps=6)
        checkpoint_id = state.create_checkpoint(
            created_by="scheduler",
            reason="initial_state",
            node_name="bootstrap",
            node_index=-1,
        )
        state.convergence.retry_counters["planner"] = 2
        state.convergence.retry_counters["supervisor:planner:re_plan"] = 1
        state.data_pool.intermediate["plan"] = {"sub_questions": ["stale"]}

        rolled_back = state.rollback_to(checkpoint_id)

        self.assertTrue(rolled_back)
        self.assertEqual(state.convergence.retry_counters["planner"], 2)
        self.assertEqual(state.convergence.retry_counters["supervisor:planner:re_plan"], 1)
        self.assertNotIn("plan", state.data_pool.intermediate)

    def test_convergence_report_captures_supervisor_replan_history(self):
        workflow = {
            "name": "guided",
            "max_steps": 8,
            "max_supervisor_revisions": 1,
            "agents": [
                {"name": "planner"},
                {"name": "search"},
                {"name": "summarizer"},
                {"name": "supervisor"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state = StateCenter(query="solid-state battery progress", max_steps=8)
            state.create_checkpoint(
                created_by="scheduler",
                reason="initial_state",
                node_name="bootstrap",
                node_index=-1,
                project_root=temp_dir,
            )
            state.data_pool.raw_documents = [{"title": "stale-doc"}]
            state.data_pool.intermediate["plan"] = {"sub_questions": ["stale-plan"]}
            state.data_pool.intermediate["summary"] = {"conclusion": "stale-summary"}
            state.create_checkpoint(
                created_by="summarizer",
                reason="post_step_success",
                node_name="summarizer",
                node_index=2,
                project_root=temp_dir,
            )
            state.data_pool.intermediate["supervisor_report"] = {
                "next_action": "revise",
                "suggested_target": "planner",
                "suggested_action": "re_plan",
            }

            next_index = scheduler._resolve_supervisor_guidance(state=state, agents=workflow["agents"])
            self.assertEqual(next_index, 0)

            _, result = scheduler._finalize_run(
                state=state,
                status="completed",
                final_node="planner",
                reason="manual finalize for audit coverage",
            )
            report = json.loads(Path(result.convergence_report_path).read_text(encoding="utf-8"))

            self.assertEqual(report["control_summary"]["checkpoint_replans"], 1)
            self.assertEqual(report["execution_audit"]["checkpoint_replan_history"][0]["target"], "planner")
            self.assertEqual(report["execution_audit"]["supervisor_guidance_history"][0]["suggested_action"], "re_plan")

    def test_memory_bundle_captures_failure_context(self):
        workflow = {
            "name": "tiny",
            "max_steps": 0,
            "agents": [{"name": "planner"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="memory failure case")

            self.assertEqual(result.status, "timed_out")
            bundle = state.data_pool.intermediate["memory_bundle"]
            self.assertEqual(bundle["failure_memory"]["status"], "timed_out")
            self.assertEqual(bundle["short_term"]["query"], "memory failure case")
            self.assertTrue(Path(result.memory_path).exists())

    def test_memory_manager_can_retrieve_and_reuse_recent_memory(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            first_state, first_result = scheduler.run(query="solid-state battery progress")
            self.assertEqual(first_result.status, "completed")

            second_state, second_result = scheduler.run(query="solid-state battery progress")
            self.assertEqual(second_result.status, "completed")

            retrieved_memories = second_state.data_pool.intermediate["retrieved_memories"]
            self.assertGreaterEqual(len(retrieved_memories), 1)
            self.assertEqual(second_state.data_pool.intermediate["plan"]["memory_hints_used"], len(retrieved_memories))

            report = json.loads(Path(second_result.convergence_report_path).read_text(encoding="utf-8"))
            self.assertGreaterEqual(report["memory_summary"]["retrieved_memory_count"], 1)

            memory_manager = MemoryManager(temp_dir)
            matches = memory_manager.retrieve(query="solid-state battery progress", top_k=2)
            self.assertGreaterEqual(len(matches), 1)
            self.assertEqual(matches[0]["memory_version"], "v1")

    def test_tool_registry_registers_and_runs_tools(self):
        registry = ToolRegistry()
        registry.register("echo_tool", "Return the payload unchanged.", lambda payload: {"payload": payload})

        result = registry.run("echo_tool", payload="hello")

        self.assertEqual(registry.list_names(), ["echo_tool"])
        self.assertEqual(result, {"payload": "hello"})

    def test_tool_registry_tracks_risk_level(self):
        registry = ToolRegistry()
        registry.register(
            "dangerous_tool",
            "High risk tool for permission checks.",
            lambda query: {"status": "blocked"},
            risk_level="high",
        )

        spec = registry.get("dangerous_tool")

        self.assertEqual(spec.risk_level, "high")

    def test_default_tool_registry_provides_mock_search_context(self):
        registry = build_default_tool_registry()

        documents = registry.run(
            "mock_search_context",
            query="support case",
            sub_questions=["What happened?"],
            plan_type="service",
        )

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["tool_name"], "mock_search_context")
        self.assertEqual(documents[0]["source_type"], "mock_context")

    def test_llm_client_profiles_and_structured_completion(self):
        client = LLMClient()

        plan = client.complete_structured(
            task="plan",
            profile="worker",
            payload={"query": "support case", "plan_type": "service"},
        )
        report = client.complete_structured(
            task="supervise",
            profile="orchestrator",
            payload={
                "query": "support case",
                "status": "running",
                "process_review": {"steps_seen": 3},
                "concerns": [],
                "review_reason": "流程完整，结果可接受",
                "suggested_target": "none",
                "suggested_action": "accept",
            },
        )

        self.assertEqual(client.get_profile("worker").model_name, "mock-worker")
        self.assertEqual(plan["model_profile"], "worker")
        self.assertEqual(report["process_review"]["model_profile"], "orchestrator")

    def test_evaluator_supports_declarative_custom_criteria(self):
        from orchestrator.models import EvalCriteriaItem

        evaluator = Evaluator()

        custom_criteria = [
            EvalCriteriaItem(
                path="packet.items",
                expected_type="list",
                action="fail",
                reason="custom_agent 必须输出至少 2 个 items",
                min_items=2,
            )
        ]

        failed = evaluator.evaluate(custom_criteria, output={"packet": {"items": ["only-one"]}})
        passed = evaluator.evaluate(custom_criteria, output={"packet": {"items": ["first", "second"]}})

        self.assertFalse(failed.passed)
        self.assertEqual(failed.action, "fail")
        self.assertTrue(passed.passed)

    def test_default_guardrail_manager_registers_core_guardrails(self):
        manager = build_default_guardrail_manager()

        self.assertEqual(
            manager.list_names(),
            ["block_sensitive_output_terms", "require_non_empty_query"],
        )

    def test_guardrails_block_empty_query_input(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="   ")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.final_node, "planner")
            self.assertIn("非空 query", result.reason)
            violations = [event for event in state.execution_trace if event.get("event") == "guardrail_violation"]
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["stage"], "input")

            report = json.loads(Path(result.convergence_report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["control_summary"]["guardrail_violations"], 1)
            self.assertEqual(report["quality_summary"]["guardrail_reasons"][0]["stage"], "input")

    def test_guardrails_block_sensitive_output(self):
        workflow = {
            "name": "sensitive_guardrail_flow",
            "max_steps": 2,
            "agents": [{"name": "sensitive_writer"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            state, result = scheduler.run(query="safe query")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.final_node, "sensitive_writer")
            self.assertIn("敏感信息护栏", result.reason)
            violations = [event for event in state.execution_trace if event.get("event") == "guardrail_violation"]
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["stage"], "output")

            report = json.loads(Path(result.convergence_report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["control_summary"]["guardrail_violations"], 1)
            self.assertEqual(
                report["execution_audit"]["guardrail_history"][0]["guardrail_name"],
                "block_sensitive_output_terms",
            )

    def test_trust_hierarchy_blocks_high_risk_tool_for_low_trust_agent(self):
        registry = ToolRegistry()
        registry.register(
            "dangerous_tool",
            "High risk tool for trust boundary testing.",
            lambda query: {"status": "should-not-run"},
            risk_level="high",
        )

        # 直接测试 agent 实例的权限检查
        agent = HighRiskToolAgent(tool_registry=registry)

        # agent 声明了 dangerous_tool，trust_level 是 low
        self.assertEqual(agent.config.trust_level, "low")

        # 调用高风险工具应该被拦截
        with self.assertRaises(ValueError) as ctx:
            agent.run_tool("dangerous_tool", query="test")

        self.assertIn("risk_level 'high'", str(ctx.exception))
        self.assertIn("trust_level 'low'", str(ctx.exception))

    def test_failure_taxonomy_classifies_timeout(self):
        record = classify_failure(
            status="timed_out",
            reason="达到最大步数限制",
            agent_name="planner",
        )
        self.assertEqual(record.category, FailureCategory.MAX_STEPS_EXCEEDED)
        self.assertEqual(record.severity, FailureSeverity.MEDIUM)

    def test_failure_taxonomy_classifies_guardrail_blocked(self):
        record = classify_failure(
            status="guardrail_blocked",
            reason="输入不能为空",
            agent_name="planner",
            event_type="guardrail_violation",
        )
        self.assertEqual(record.category, FailureCategory.GUARDRAIL_BLOCKED)
        self.assertEqual(record.severity, FailureSeverity.HIGH)

    def test_failure_taxonomy_classifies_permission_denied(self):
        record = classify_failure(
            status="failed",
            reason="Agent 'worker' with trust_level 'low' cannot use tool 'dangerous' with risk_level 'high'",
            agent_name="worker",
        )
        self.assertEqual(record.category, FailureCategory.TRUST_LEVEL_INSUFFICIENT)
        self.assertEqual(record.severity, FailureSeverity.HIGH)

    def test_failure_taxonomy_classifies_retry_exhausted(self):
        record = classify_failure(
            status="failed",
            reason="planner 超过最大重试次数：3",
            agent_name="planner",
        )
        self.assertEqual(record.category, FailureCategory.RETRY_EXHAUSTED)
        self.assertEqual(record.severity, FailureSeverity.MEDIUM)

    def test_convergence_report_includes_failure_summary(self):
        workflow = {
            "name": "failure_test",
            "max_steps": 0,
            "agents": [{"name": "planner"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=temp_dir)
            _, result = scheduler.run(query="test failure classification")

            self.assertEqual(result.status, "timed_out")
            report = json.loads(Path(result.convergence_report_path).read_text(encoding="utf-8"))
            self.assertTrue(report["failure_summary"]["has_failure"])
            self.assertEqual(report["failure_summary"]["category"], "max_steps_exceeded")

    def test_analyze_list_recent_runs(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            scheduler.run(query="test analyze list")

            analyzer = RunAnalyzer(Path(temp_dir))
            runs = analyzer.list_recent_runs(limit=5)

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "completed")
            self.assertEqual(runs[0]["workflow"], "deep_research")

    def test_analyze_get_run_detail(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            state, result = scheduler.run(query="test analyze detail")

            analyzer = RunAnalyzer(Path(temp_dir))
            detail = analyzer.get_run_detail(state.metadata.task_id)

            self.assertIsNotNone(detail)
            self.assertEqual(detail["task_id"], state.metadata.task_id)
            self.assertEqual(detail["status"], "completed")
            self.assertIn("flow_summary", detail)

    def test_analyze_failure_statistics(self):
        workflow = {
            "name": "failure_stats_test",
            "max_steps": 0,
            "agents": [{"name": "planner"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            scheduler.run(query="test failure stats")

            analyzer = RunAnalyzer(Path(temp_dir))
            stats = analyzer.get_failure_statistics()

            self.assertEqual(stats["total_runs"], 1)
            self.assertEqual(stats["failed_runs"], 1)
            self.assertIn("max_steps_exceeded", stats["failure_categories"])

    def test_analyze_agent_performance(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            scheduler.run(query="test agent performance")

            analyzer = RunAnalyzer(Path(temp_dir))
            stats = analyzer.get_agent_performance()

            self.assertGreaterEqual(stats["total_evaluations"], 3)
            self.assertIn("planner", stats["agents"])
            self.assertIn("search", stats["agents"])
            self.assertIn("summarizer", stats["agents"])

    def test_analyze_memory_summary(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            scheduler.run(query="test memory summary")

            analyzer = RunAnalyzer(Path(temp_dir))
            summary = analyzer.get_memory_summary()

            self.assertEqual(summary["total_memories"], 1)
            self.assertIn("research", summary["by_plan_type"])
            self.assertEqual(len(summary["recent_memories"]), 1)

    def test_llm_providers_registry_lists_available_providers(self):
        from orchestrator.llm_providers import list_providers

        providers = list_providers()
        self.assertIn("mock", providers)
        self.assertIn("glm", providers)
        self.assertIn("kimi", providers)
        self.assertIn("openai", providers)
        self.assertIn("anthropic", providers)

    def test_llm_client_supports_mock_provider(self):
        from orchestrator.llm_client import LLMClient

        client = LLMClient(provider="mock")
        self.assertEqual(client.provider_name, "mock")

        result = client.complete_structured(
            task="plan",
            profile="worker",
            payload={"query": "test", "plan_type": "research"},
        )
        self.assertIn("sub_questions", result)

    def test_llm_client_supports_custom_provider_instance(self):
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        mock_provider = MockProvider()
        client = LLMClient(provider=mock_provider)

        self.assertEqual(client.provider_name, "mock")

        raw = client.complete("test prompt", model="test-model")
        self.assertIn("Mock response", raw)

    def test_llm_client_builds_prompts_for_different_tasks(self):
        from orchestrator.llm_client import LLMClient

        client = LLMClient(provider="mock")

        # Plan task
        plan_prompt = client._build_prompt(
            task="plan",
            payload={"query": "Python async", "plan_type": "research"},
        )
        self.assertIn("Python async", plan_prompt)
        self.assertIn("sub_questions", plan_prompt)

        # Summarize task
        summarize_prompt = client._build_prompt(
            task="summarize",
            payload={
                "query": "Python async",
                "plan_type": "research",
                "sub_questions": ["What is async?"],
                "raw_documents": [{"title": "test", "snippet": "content"}],
            },
        )
        self.assertIn("Python async", summarize_prompt)
        self.assertIn("What is async?", summarize_prompt)

    def test_agent_config_supports_llm_provider_field(self):
        from orchestrator.models import AgentConfig, WriteSpec

        config = AgentConfig(
            name="test_agent",
            reads=["query"],
            writes=[WriteSpec(field="result")],
            llm_provider="glm",
            llm_model="GLM-5.1",
        )

        self.assertEqual(config.llm_provider, "glm")
        self.assertEqual(config.llm_model, "GLM-5.1")

    def test_cli_agent_command_supports_llm_provider(self):
        from orchestrator.registry import get_agent
        from orchestrator.llm_providers import MockProvider

        agent_cls = get_agent("planner")
        mock_provider = MockProvider()
        agent = agent_cls(llm_provider=mock_provider)

        self.assertEqual(agent.llm_client.provider_name, "mock")

    def test_codex_provider_prefers_output_file_and_stdin(self):
        from unittest.mock import patch
        from orchestrator.llm_providers import CodexProvider

        provider = CodexProvider(timeout=5)

        def fake_run(cmd, **kwargs):
            self.assertIn("-o", cmd)
            self.assertEqual(cmd[-1], "-")
            self.assertEqual(kwargs["input"], "Reply with exactly: ok")
            output_index = cmd.index("-o") + 1
            Path(cmd[output_index]).write_text("ok", encoding="utf-8")

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch.object(provider, "_resolve_codex_command", return_value=["codex.exe"]):
            with patch("orchestrator.llm_providers.subprocess.run", side_effect=fake_run):
                result = provider.complete(
                    "Reply with exactly: ok",
                    model="gpt-5.4",
                )

        self.assertEqual(result, "ok")

    def test_describe_providers_reflects_configuration(self):
        from unittest.mock import patch
        from orchestrator.llm_providers import describe_providers

        env = {
            "GLM_API_KEY": "glm-key",
            "GLM_API_BASE": "https://api.example.com/v1",
            "DEEPSEEK_API_KEY": "deepseek-key",
        }

        def fake_which(name: str):
            if name == "codex.exe":
                return r"C:\tools\codex.exe"
            return None

        with patch.dict("os.environ", env, clear=True):
            with patch("orchestrator.llm_providers.shutil.which", side_effect=fake_which):
                providers = {provider.name: provider for provider in describe_providers()}

        self.assertTrue(providers["glm"].configured)
        self.assertEqual(providers["glm"].api_base, "https://api.example.com/v1")
        self.assertEqual(providers["glm"].default_model, "GLM-5.1")
        self.assertTrue(providers["deepseek"].configured)
        self.assertTrue(providers["codex"].available)
        self.assertFalse(providers["kimi"].configured)

    def test_openai_compatible_provider_formats_502_error(self):
        from unittest.mock import patch
        import httpx
        from orchestrator.llm_providers import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            name="glm",
            api_key="glm-key",
            api_base="https://api.example.com/v1",
        )

        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        response = httpx.Response(502, request=request, text="bad gateway")

        class FakeClient:
            def post(self, *args, **kwargs):
                raise httpx.HTTPStatusError("bad gateway", request=request, response=response)

            def close(self):
                return None

        with patch.object(provider, "_get_client", return_value=FakeClient()):
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete("hello", model="GLM-5.1")

        self.assertIn("HTTP 502", str(ctx.exception))
        self.assertIn("GLM-5.1", str(ctx.exception))
        self.assertIn("api.example.com", str(ctx.exception))

    def test_completed_run_uses_completion_reason_not_failure_reason(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            state, _ = scheduler.run(query="solid-state battery progress")

            self.assertEqual(state.metadata.status, "completed")
            self.assertEqual(state.metadata.failure_reason, "")
            self.assertEqual(state.metadata.completion_reason, "工作流末尾节点已完成")

            report_path = Path(temp_dir) / "outputs" / "reports" / f"{state.metadata.task_id}.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["failure_reason"], "")
            self.assertEqual(report["completion_reason"], "工作流末尾节点已完成")

    def test_regression_summary_is_readable_and_skips_guardrail_only_cases(self):
        workflow = load_workflow(Path("workflows/deep_research.yaml"))
        with tempfile.TemporaryDirectory() as temp_dir:
            scheduler = Scheduler(workflow=workflow, project_root=Path(temp_dir))
            _, good_result = scheduler.run(query="solid-state battery progress")
            _, blocked_result = scheduler.run(query="   ")
            _, second_good_result = scheduler.run(query="another research query")

            comparer = RegressionCompare(Path(temp_dir))
            regressions = comparer.find_regressions(limit=10)

            task_pairs = {(report.old_task_id, report.new_task_id) for report in regressions}
            self.assertNotIn((good_result.task_id, blocked_result.task_id), task_pairs)
            self.assertEqual(len(regressions), 0)

            comparisons = comparer.compare_recent(limit=10)
            summaries = [report.summary for report in comparisons]
            self.assertTrue(any("regression detected" in summary.lower() or "improvement detected" in summary.lower() for summary in summaries))
            self.assertFalse(any("?" in summary for summary in summaries))

    def test_ask_infers_deep_research_workflow_by_default(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Help me research solid-state battery progress",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research.yaml")

    def test_ask_infers_customer_support_workflow_for_support_queries(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Draft a reply plan for a delayed shipment support ticket",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "customer_support_brief.yaml")

    def test_ask_infers_human_review_workflow_for_human_approval_intent(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Research solid-state battery progress and need human approval",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_human_review.yaml")

    def test_ask_infers_human_review_workflow_for_chinese_human_confirm_intent(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="研究固态电池进展，需要人工确认",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_human_review.yaml")

    def test_ask_infers_supervised_workflow_for_supervisor_review_intent(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Research solid-state battery progress with supervisor review",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_supervised.yaml")

    def test_ask_infers_supervised_workflow_for_chinese_supervisor_intent(self):
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="研究固态电池进展，需要复核",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_supervised.yaml")

    def test_ask_human_review_priority_over_support(self):
        """Human review intent should take priority over support keywords."""
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Handle this support ticket with human confirmation",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_human_review.yaml")

    def test_ask_supervised_priority_over_support(self):
        """Supervised intent should take priority over support keywords."""
        from orchestrator.__main__ import _infer_workflow_path

        workflow_path = _infer_workflow_path(
            query="Handle this support ticket requiring supervisor review",
            project_root=Path.cwd(),
        )

        self.assertEqual(workflow_path.name, "deep_research_supervised.yaml")

    def test_llm_router_returns_deep_research(self):
        """LLM router returning deep_research should route to deep_research.yaml."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        # Create a mock provider that returns "deep_research"
        class DeepResearchMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "deep_research"

        client = LLMClient(provider=DeepResearchMockProvider())
        result = _route_workflow_with_llm("Research AI trends", client)
        self.assertEqual(result, "deep_research")

    def test_llm_router_returns_customer_support_brief(self):
        """LLM router returning customer_support_brief should route correctly."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class SupportMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "customer_support_brief"

        client = LLMClient(provider=SupportMockProvider())
        result = _route_workflow_with_llm("Help with customer ticket", client)
        self.assertEqual(result, "customer_support_brief")

    def test_llm_router_fallback_on_invalid_value(self):
        """LLM router returning invalid value should return None (triggers fallback)."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class InvalidMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "invalid_workflow_name"

        client = LLMClient(provider=InvalidMockProvider())
        result = _route_workflow_with_llm("Some query", client)
        self.assertIsNone(result)

    def test_llm_router_fallback_on_exception(self):
        """LLM router raising exception should return None (triggers fallback)."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class ExceptionMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                raise RuntimeError("LLM error")

        client = LLMClient(provider=ExceptionMockProvider())
        result = _route_workflow_with_llm("Some query", client)
        self.assertIsNone(result)

    def test_resolve_workflow_for_ask_uses_llm_router(self):
        """_resolve_workflow_for_ask should use LLM router when available."""
        from orchestrator.__main__ import _resolve_workflow_for_ask
        from orchestrator.llm_providers import MockProvider

        class SupervisedMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "deep_research_supervised"

        llm_config = {"global_provider": None, "global_model": None, "agent_llm": None}
        # This will use mock provider, which is skipped for routing
        # So it should fallback to rules
        workflow_path = _resolve_workflow_for_ask(
            query="Research AI trends",
            project_root=Path.cwd(),
            llm_config=llm_config,
        )
        self.assertEqual(workflow_path.name, "deep_research.yaml")

    def test_resolve_workflow_fallback_to_rules_on_llm_failure(self):
        """When LLM router fails, should fallback to rule-based routing."""
        from orchestrator.__main__ import _resolve_workflow_for_ask

        # Use mock provider (which is skipped for routing, triggering fallback)
        llm_config = {"global_provider": None, "global_model": None, "agent_llm": None}
        workflow_path = _resolve_workflow_for_ask(
            query="This support ticket needs handling",
            project_root=Path.cwd(),
            llm_config=llm_config,
        )
        # Should fallback to rules, which detects "support" and "ticket"
        self.assertEqual(workflow_path.name, "customer_support_brief.yaml")

    def test_resolve_workflow_uses_llm_result_with_non_mock_provider(self):
        """_resolve_workflow_for_ask should use LLM router result with non-mock provider."""
        from unittest.mock import patch
        from orchestrator.__main__ import _resolve_workflow_for_ask
        from orchestrator.llm_providers import MockProvider

        class FakeNonMockProvider(MockProvider):
            name = "fake_non_mock"

            def complete(self, prompt, **kwargs):
                return "deep_research_human_review"

        llm_config = {"global_provider": "fake_non_mock", "global_model": None, "agent_llm": None}

        with patch("orchestrator.llm_providers.get_provider", return_value=FakeNonMockProvider()):
            workflow_path = _resolve_workflow_for_ask(
                query="Research AI trends",
                project_root=Path.cwd(),
                llm_config=llm_config,
            )
        # LLM router returned "deep_research_human_review", should be used
        self.assertEqual(workflow_path.name, "deep_research_human_review.yaml")

    def test_resolve_workflow_fallback_when_llm_returns_invalid_with_non_mock_provider(self):
        """_resolve_workflow_for_ask should fallback to rules when LLM returns invalid value."""
        from unittest.mock import patch
        from orchestrator.__main__ import _resolve_workflow_for_ask
        from orchestrator.llm_providers import MockProvider

        class FakeNonMockProvider(MockProvider):
            name = "fake_non_mock"

            def complete(self, prompt, **kwargs):
                return "invalid_workflow_name"

        llm_config = {"global_provider": "fake_non_mock", "global_model": None, "agent_llm": None}

        with patch("orchestrator.llm_providers.get_provider", return_value=FakeNonMockProvider()):
            workflow_path = _resolve_workflow_for_ask(
                query="This support ticket needs handling",
                project_root=Path.cwd(),
                llm_config=llm_config,
            )
        # LLM returned invalid value, should fallback to rules (detects "support" and "ticket")
        self.assertEqual(workflow_path.name, "customer_support_brief.yaml")

    def test_llm_router_strict_match_rejects_substring(self):
        """LLM router should reject substring matches, only accept exact matches."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class SubstringMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "deep_research is the best choice"

        client = LLMClient(provider=SubstringMockProvider())
        result = _route_workflow_with_llm("Research AI trends", client)
        # Should return None because "deep_research is the best choice" != "deep_research"
        self.assertIsNone(result)

    def test_llm_router_normalizes_double_quotes(self):
        """LLM router should recognize workflow name wrapped in double quotes."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class QuotedMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return '"deep_research"'

        client = LLMClient(provider=QuotedMockProvider())
        result = _route_workflow_with_llm("Research AI trends", client)
        self.assertEqual(result, "deep_research")

    def test_llm_router_normalizes_backticks(self):
        """LLM router should recognize workflow name wrapped in backticks."""
        from orchestrator.__main__ import _route_workflow_with_llm
        from orchestrator.llm_client import LLMClient
        from orchestrator.llm_providers import MockProvider

        class BacktickMockProvider(MockProvider):
            def complete(self, prompt, **kwargs):
                return "`deep_research_supervised`"

        client = LLMClient(provider=BacktickMockProvider())
        result = _route_workflow_with_llm("Research AI trends", client)
        self.assertEqual(result, "deep_research_supervised")


if __name__ == "__main__":
    unittest.main()
