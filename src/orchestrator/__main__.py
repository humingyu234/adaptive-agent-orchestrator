import argparse
import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

from . import agents as _agents  # noqa: F401
from .analyze import RunAnalyzer, format_table
from .cli_output import build_raw_payload, build_run_payload, format_run_text
from .llm_providers import describe_providers, list_providers
from .project_context import ProjectContext
from .live_view import build_live_view, is_terminal, render_live_view
from .regression_compare import RegressionCompare, RegressionSignal, format_regression_report

from .project_session import (
    DecisionLog,
    ProjectMilestone,
    ProjectRunLink,
    ProjectSessionStore,
    SessionContext,
    _new_id,
    _now,
)
from .eval_prompts import (
    EvalSummary,
    eval_summary_to_dict,
    render_eval_summary,
    run_eval_cases,
)
from .mainline_executor import MainlineExecutor
from .planning import (
    PlanningCouncil,
    PlanContract,
    PlanningMode,
    build_default_council,
    plan_contract_to_dict,
    render_plan_contract,
)
from .task_router import (
    requires_future_runner,
    route_task,
    render_route_decision,
    route_decision_to_dict,
    should_execute_workflow,
    should_only_log,
)
from .registry import REGISTRY, get_agent
from .scheduler import Scheduler
from .state_center import StateCenter
from .workflow import load_workflow


def _load_optional_dotenv() -> None:
    if load_dotenv is None:
        return
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive Agent Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Run a task from a natural-language prompt")
    ask_parser.add_argument("query", help="Task request in natural language")
    ask_parser.add_argument("--llm", help="Optional global LLM provider override")
    ask_parser.add_argument("--model", help="Optional global model override")
    ask_parser.add_argument("--agent-llm", help="Optional per-agent LLM config, format: agent=provider:model")
    ask_parser.add_argument("--raw", action="store_true", help="Print legacy internal result/state payload")
    ask_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")
    ask_parser.add_argument("--mode", choices=["off", "log", "controlled", "orchestrated"], help="Override the default run mode")
    ask_parser.add_argument("--force-run", action="store_true", help="Force workflow execution even for log/off routes")
    ask_parser.add_argument("--approve", action="store_true", help="Auto-approve plan for complex/orchestrated tasks")
    ask_parser.add_argument("--worker-mode", choices=["fake", "packet", "claude-code"], help="Use mainline executor with specified worker (skips legacy YAML workflow)")
    ask_parser.add_argument("--planning-mode", choices=["deterministic", "llm"], default="deterministic", help="Planning Council mode (default: deterministic)")
    ask_parser.add_argument("--max-workers", type=int, default=2, help="Maximum concurrent workers for multi-worker execution (default: 2)")

    review_parser = subparsers.add_parser("review", help="Approve or reject a paused human review task")
    review_parser.add_argument("--task-id", required=True, help="Task ID waiting for human review")
    review_parser.add_argument("--decision", required=True, choices=["approve", "reject"], help="Human review decision")
    review_parser.add_argument("--reason", default="", help="Optional human review reason")
    review_parser.add_argument("--workflow", help="Optional workflow path override")
    review_parser.add_argument("--raw", action="store_true", help="Print legacy internal result/state payload")
    review_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")

    resume_parser = subparsers.add_parser("resume", help="Resume a paused human review task")
    resume_parser.add_argument("--task-id", required=True, help="Task ID waiting for human review")
    resume_parser.add_argument("--decision", required=True, choices=["approve", "reject"], help="Human review decision")
    resume_parser.add_argument("--reason", default="", help="Optional human review reason")
    resume_parser.add_argument("--workflow", help="Optional workflow path override")
    resume_parser.add_argument("--raw", action="store_true", help="Print legacy internal result/state payload")
    resume_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")

    run_parser = subparsers.add_parser("run", help="Run a workflow against a query")
    run_parser.add_argument("--workflow", required=True, help="Path to workflow yaml")
    run_parser.add_argument("--query", required=True, help="Task query to execute")
    run_parser.add_argument("--llm", help="LLM provider to use (glm/openai/anthropic/codex/deepseek/ollama)")
    run_parser.add_argument("--model", help="Model name to use")
    run_parser.add_argument("--agent-llm", help="Per-agent LLM config, format: agent=provider:model")
    run_parser.add_argument("--raw", action="store_true", help="Print legacy internal result/state payload")
    run_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")
    run_parser.add_argument("--mode", choices=["off", "log", "controlled", "orchestrated"], help="Override the default run mode")
    run_parser.add_argument("--force-run", action="store_true", help="Force workflow execution even for log/off routes")
    run_parser.add_argument("--approve", action="store_true", help="Auto-approve plan for complex/orchestrated tasks")
    run_parser.add_argument("--planning-mode", choices=["deterministic", "llm"], default="deterministic", help="Planning Council mode (default: deterministic)")
    run_parser.add_argument("--max-workers", type=int, default=2, help="Maximum concurrent workers for multi-worker execution (default: 2)")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze historical runs")
    analyze_subparsers = analyze_parser.add_subparsers(dest="analyze_command", required=True)

    list_parser = analyze_subparsers.add_parser("list", help="List recent runs")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of runs to show")

    show_parser = analyze_subparsers.add_parser("show", help="Show run detail")
    show_parser.add_argument("--task-id", required=True, help="Task ID to show")

    failures_parser = analyze_subparsers.add_parser("failures", help="Show failure statistics")
    failures_parser.add_argument("--limit", type=int, default=50, help="Number of runs to analyze")

    agents_stats_parser = analyze_subparsers.add_parser("agents", help="Show agent performance statistics")
    agents_stats_parser.add_argument("--limit", type=int, default=50, help="Number of runs to analyze")

    analyze_subparsers.add_parser("memory", help="Show memory index summary")

    health_parser = analyze_subparsers.add_parser("health", help="Show agent health score")
    health_parser.add_argument("--agent", help="Agent name (omit to show all)")
    health_parser.add_argument("--days", type=int, default=7, help="Days to analyze")

    agent_failures_parser = analyze_subparsers.add_parser("agent-failures", help="Show agent failure cases")
    agent_failures_parser.add_argument("--agent", required=True, help="Agent name")
    agent_failures_parser.add_argument("--limit", type=int, default=10, help="Number of failures to show")

    regression_parser = analyze_subparsers.add_parser("regression", help="Compare runs for regression detection")
    regression_parser.add_argument("--old", help="Old task ID")
    regression_parser.add_argument("--new", help="New task ID")
    regression_parser.add_argument("--workflow", help="Filter by workflow name")
    regression_parser.add_argument("--recent", type=int, help="Compare recent N adjacent runs")
    regression_parser.add_argument("--find", type=int, help="Find regressions in recent N runs")

    agent_parser = subparsers.add_parser("agent", help="Run a single agent")
    agent_parser.add_argument("--name", required=True, help="Agent name to run")
    agent_parser.add_argument("--query", required=True, help="Query string")
    agent_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    agent_parser.add_argument("--llm", help="LLM provider to use")
    agent_parser.add_argument("--model", help="Model name to use")

    agents_parser = subparsers.add_parser("agents", help="List available agents")
    agents_parser.add_argument("--verbose", action="store_true", help="Show detailed info")

    providers_parser = subparsers.add_parser("providers", help="List configured LLM providers")
    providers_parser.add_argument("--verbose", action="store_true", help="Show detailed provider info")

    context_parser = subparsers.add_parser("project-context", help="Show project file context")
    context_parser.add_argument("--scan", action="store_true", help="Scan project structure")
    context_parser.add_argument("--file", help="Show specific file summary")
    context_parser.add_argument("--find", help="Find files matching pattern")
    context_parser.add_argument("--extension", help="Filter by file extension")
    context_parser.add_argument("--max-depth", type=int, help="Maximum scan depth")

    route_parser = subparsers.add_parser("route", help="Route a task without executing it")
    route_parser.add_argument("query", help="Task request in natural language")
    route_parser.add_argument("--mode", choices=["off", "log", "controlled", "orchestrated"], help="Override the default run mode")
    route_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")

    plan_parser = subparsers.add_parser("plan", help="Generate a plan contract for a complex task")
    plan_parser.add_argument("query", help="Task request in natural language")
    plan_parser.add_argument("--mode", choices=["off", "log", "controlled", "orchestrated"], help="Override the default run mode")
    plan_parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format (default: json)")
    plan_parser.add_argument("--approve", action="store_true", help="Auto-approve the plan (skip approval prompt)")
    plan_parser.add_argument("--reject", action="store_true", help="Reject the plan")
    plan_parser.add_argument("--planning-mode", choices=["deterministic", "llm"], default="deterministic", help="Planning Council mode (default: deterministic)")

    eval_parser = subparsers.add_parser("eval-prompts", help="Evaluate prompt quality against golden planning cases")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)

    eval_planning_parser = eval_subparsers.add_parser("planning", help="Evaluate planning prompts against golden cases")
    eval_planning_parser.add_argument("--mode", choices=["deterministic", "llm"], default="deterministic", help="Planning mode (default: deterministic)")
    eval_planning_parser.add_argument("--cases", default="tests/golden/planning_cases.yaml", help="Path to golden cases YAML (default: tests/golden/planning_cases.yaml)")
    eval_planning_parser.add_argument("--repeat", type=int, default=1, help="Repeat count for statistical confidence (default: 1)")
    eval_planning_parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format (default: text)")
    eval_planning_parser.add_argument("--verbose", action="store_true", help="Print per-case errors to stderr")
    eval_planning_parser.add_argument("--provider", default="deepseek", help="LLM provider for all three advisors (default: deepseek; env vars AAO_PLANNER_PROVIDER etc. override per-role)")

    status_parser = subparsers.add_parser("status", help="Show live run status for a task")
    status_parser.add_argument("--task-id", required=True, help="Task ID to show status for")

    watch_parser = subparsers.add_parser("watch", help="Watch run status in real time (refreshes until terminal)")
    watch_parser.add_argument("--task-id", required=True, help="Task ID to watch")
    watch_parser.add_argument("--once", action="store_true", help="Render once and exit (no polling)")
    watch_parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1.0)")

    worker_parser = subparsers.add_parser("worker", help="Create and inspect worker task packets")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)

    worker_create_parser = worker_subparsers.add_parser("create", help="Create a worker task packet")
    worker_create_parser.add_argument("--objective", required=True, help="Task objective")
    worker_create_parser.add_argument("--title", help="Task title (defaults to objective prefix)")
    worker_create_parser.add_argument("--allowed", nargs="*", default=[], help="Allowed file paths")
    worker_create_parser.add_argument("--denied", nargs="*", default=[], help="Denied file paths")
    worker_create_parser.add_argument("--protected", nargs="*", default=[], help="Protected file paths")
    worker_create_parser.add_argument("--check", nargs="*", default=[], dest="checks", help="Required check commands")
    worker_create_parser.add_argument("--evidence", nargs="*", default=[], help="Expected evidence keys")
    worker_create_parser.add_argument("--risk", choices=["low", "medium", "high"], default="low", help="Risk level")
    worker_create_parser.add_argument("--mode", choices=["off", "log", "controlled", "orchestrated"], default="controlled", help="Run mode")
    worker_create_parser.add_argument("--run-id", default="", help="Run ID (auto-generated if omitted)")
    worker_create_parser.add_argument("--task-id", default="", help="Task ID (auto-generated if omitted)")

    worker_inspect_parser = worker_subparsers.add_parser("inspect", help="Inspect a completed worker task packet")
    worker_inspect_parser.add_argument("path", help="Path to the packet directory (.aao/tasks/<run_id>/<task_id>)")

    # ---- project (Phase 24) ----
    project_parser = subparsers.add_parser("project", help="Manage project sessions")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)

    project_start_parser = project_subparsers.add_parser("start", help="Create a new project session")
    project_start_parser.add_argument("goal", help="Project goal description")
    project_start_parser.add_argument("--project-id", help="Custom project ID (auto-generated if omitted)")
    project_start_parser.add_argument("--planning-mode", choices=["deterministic", "llm"], default="deterministic", help="Planning Council mode (default: deterministic)")

    project_status_parser = project_subparsers.add_parser("status", help="Show current project status")
    project_status_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    project_ask_parser = project_subparsers.add_parser("ask", help="Ask a question about project history")
    project_ask_parser.add_argument("question", help="Question about the project")
    project_ask_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    project_continue_parser = project_subparsers.add_parser("continue", help="Resume the current project")
    project_continue_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    project_close_parser = project_subparsers.add_parser("close", help="Close the current project")
    project_close_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    # Phase 25 — Milestone Gate
    project_approve_parser = project_subparsers.add_parser("approve", help="Approve a milestone and continue to the next")
    project_approve_parser.add_argument("milestone_id", help="Milestone ID to approve")
    project_approve_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    project_reject_parser = project_subparsers.add_parser("reject", help="Reject a milestone with a reason")
    project_reject_parser.add_argument("milestone_id", help="Milestone ID to reject")
    project_reject_parser.add_argument("--reason", default="", help="Reason for rejection")
    project_reject_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    project_request_changes_parser = project_subparsers.add_parser("request-changes", help="Request changes to a milestone")
    project_request_changes_parser.add_argument("milestone_id", help="Milestone ID to request changes for")
    project_request_changes_parser.add_argument("--notes", default="", help="Notes describing what needs to change")
    project_request_changes_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")

    # Phase 27 — Self-Check
    project_self_check_parser = project_subparsers.add_parser("self-check", help="Check AAO control chain for system issues")
    project_self_check_parser.add_argument("--project-id", help="Project ID (uses latest active if omitted)")
    project_self_check_parser.add_argument("--category", choices=["evidence_false_positive", "isolation_violation", "resume_broken", "worker_bridge_bypass", "plan_reality_drift", "decision_inconsistency"], help="Run a specific self-check category only")

    args = parser.parse_args()

    if args.command == "ask":
        _handle_ask_command(args)
    elif args.command == "review":
        _handle_review_command(args)
    elif args.command == "resume":
        _handle_review_command(args)
    elif args.command == "run":
        _handle_run_command(args)
    elif args.command == "analyze":
        _handle_analyze_command(args)
    elif args.command == "agent":
        _handle_agent_command(args)
    elif args.command == "agents":
        _handle_agents_command(args)
    elif args.command == "providers":
        _handle_providers_command(args)
    elif args.command == "project-context":
        _handle_project_context_command(args)
    elif args.command == "route":
        _handle_route_command(args)
    elif args.command == "plan":
        _handle_plan_command(args)
    elif args.command == "eval-prompts":
        _handle_eval_prompts_command(args)
    elif args.command == "status":
        _handle_status_command(args)
    elif args.command == "watch":
        _handle_watch_command(args)
    elif args.command == "worker":
        _handle_worker_command(args)
    elif args.command == "project":
        _handle_project_command(args)


def _handle_analyze_command(args) -> None:
    project_root = Path.cwd()
    analyzer = RunAnalyzer(project_root)

    if args.analyze_command == "list":
        runs = analyzer.list_recent_runs(limit=args.limit)
        if not runs:
            print("No runs found.")
            return
        rows = [
            [r["task_id"][:8], r["workflow"], r["query"], r["status"], r["steps"], r["created_at"]]
            for r in runs
        ]
        print(format_table(rows, ["ID", "Workflow", "Query", "Status", "Steps", "Time"]))
        return

    if args.analyze_command == "show":
        detail = analyzer.get_run_detail(args.task_id)
        if not detail:
            print(f"Run not found: {args.task_id}")
            return
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return

    if args.analyze_command == "failures":
        stats = analyzer.get_failure_statistics(limit=args.limit)
        print(f"Total runs: {stats['total_runs']}")
        print(f"Failed runs: {stats['failed_runs']}")
        print()
        if stats["failure_categories"]:
            print("Failure categories:")
            for cat, count in sorted(stats["failure_categories"].items(), key=lambda x: -x[1]):
                print(f"  {cat}: {count}")
            print()
        if stats["failure_severities"]:
            print("Failure severities:")
            for sev, count in sorted(stats["failure_severities"].items(), key=lambda x: -x[1]):
                print(f"  {sev}: {count}")
            print()
        if stats["recent_failures"]:
            print("Recent failures:")
            rows = [
                [f["task_id"][:8], f["category"], f["severity"], f["agent"], f["reason"]]
                for f in stats["recent_failures"][:10]
            ]
            print(format_table(rows, ["ID", "Category", "Severity", "Agent", "Reason"]))
        return

    if args.analyze_command == "agents":
        stats = analyzer.get_agent_performance(limit=args.limit)
        print(f"Total evaluations: {stats['total_evaluations']}")
        print(f"Failed evaluations: {stats['total_failed_evaluations']}")
        print()
        if stats["agents"]:
            print("Agent statistics:")
            rows = [
                [name, data["runs"], ", ".join(data["tools_used"]) or "-"]
                for name, data in sorted(stats["agents"].items())
            ]
            print(format_table(rows, ["Agent", "Runs", "Tools"]))
        return

    if args.analyze_command == "memory":
        summary = analyzer.get_memory_summary()
        print(f"Total memories: {summary['total_memories']}")
        print()
        if summary["by_plan_type"]:
            print("By plan type:")
            for plan_type, count in sorted(summary["by_plan_type"].items(), key=lambda item: str(item[0])):
                print(f"  {plan_type}: {count}")
            print()
        if summary["recent_memories"]:
            print("Recent memories:")
            rows = [
                [m["task_id"][:8], m["query"], m["plan_type"], m["captured_at"]]
                for m in summary["recent_memories"]
            ]
            print(format_table(rows, ["ID", "Query", "Type", "Time"]))
        return

    if args.analyze_command == "health":
        if args.agent:
            health = analyzer.get_agent_health(args.agent, days=args.days)
            print(f"Agent: {health['agent']}")
            print(f"Period: {health['period_days']} days")
            print(f"Total runs: {health['total_runs']}")
            print(f"Success: {health['success_runs']}, Failed: {health['failed_runs']}")
            print(f"Success rate: {health['success_rate']:.1%}")
            print(f"Health score: {health['health_score']} ({health['health_level']})")
            if health["recent_failures"]:
                print("\nRecent failures:")
                rows = [[f["task_id"][:8], f["category"], f["reason"]] for f in health["recent_failures"][:5]]
                print(format_table(rows, ["ID", "Category", "Reason"]))
        else:
            all_health = analyzer.get_all_agents_health(days=args.days)
            rows = [
                [name, h["total_runs"], h["success_runs"], h["failed_runs"], f"{h['success_rate']:.1%}", h["health_score"], h["health_level"]]
                for name, h in sorted(all_health.items())
            ]
            print(format_table(rows, ["Agent", "Total", "Success", "Failed", "Rate", "Score", "Level"]))
        return

    if args.analyze_command == "agent-failures":
        failures = analyzer.get_agent_failures(args.agent, limit=args.limit)
        if not failures:
            print(f"No failures found for agent '{args.agent}'.")
            return
        print(f"Failures for agent '{args.agent}':\n")
        for i, failure in enumerate(failures, 1):
            print(f"{i}. Task: {failure['task_id'][:8]}")
            print(f"   Query: {failure['query']}")
            print(f"   Reason: {failure['reason']}")
            print(f"   Category: {failure['category']}, Severity: {failure['severity']}")
            print(f"   Time: {failure['timestamp']}")
            print()
        return

    if args.analyze_command == "regression":
        comparator = RegressionCompare(project_root)
        if args.old and args.new:
            report = comparator.compare(args.old, args.new, args.workflow)
            print(format_regression_report(report))
            return
        if args.recent:
            reports = comparator.compare_recent(limit=args.recent, workflow_name=args.workflow)
            for report in reports:
                print(format_regression_report(report))
                print()
            return
        if args.find:
            regressions = comparator.find_regressions(
                threshold=RegressionSignal.MINOR_REGRESSION,
                workflow_name=args.workflow,
                limit=args.find,
            )
            scope = f"recent {args.find} runs"
            if args.workflow:
                scope = f"workflow={args.workflow}, {scope}"
            if not regressions:
                print(f"No meaningful regressions found in {scope}.")
            else:
                print(f"Found {len(regressions)} large run-to-run differences in {scope}:\n")
                for report in regressions:
                    workflow = report.workflow_name or "unknown"
                    print(f"  [{workflow}] {report.old_task_id[:8]} -> {report.new_task_id[:8]}: {report.signal.value}")
                    print(f"    {report.summary}")
            return
        print("Please specify --old/--new, --recent, or --find")


def _handle_route_command(args) -> None:
    """Route a task without executing it — prints the route decision."""
    explicit_mode = getattr(args, "mode", None)
    decision = route_task(args.query, explicit_mode=explicit_mode)

    fmt = getattr(args, "format", "json")
    if fmt == "text":
        print(render_route_decision(decision))
    else:
        print(json.dumps(route_decision_to_dict(decision), ensure_ascii=False, indent=2))


def _handle_plan_command(args) -> None:
    """Generate a plan contract for a task — no execution."""
    _load_optional_dotenv()
    explicit_mode = getattr(args, "mode", None)
    decision = route_task(args.query, explicit_mode=explicit_mode)

    planning_mode: PlanningMode = getattr(args, "planning_mode", "deterministic")
    council = build_default_council(mode=planning_mode)
    plan = council.create_plan(
        args.query,
        task_size=decision.task_size,
        run_mode=decision.run_mode,
        risk_level=decision.risk_level,
        task_type=decision.task_type,
    )

    # Apply approval/rejection if requested
    if getattr(args, "approve", False):
        plan.approve()
    elif getattr(args, "reject", False):
        plan.reject()

    fmt = getattr(args, "format", "json")
    if fmt == "text":
        print(render_plan_contract(plan))
    else:
        output = plan_contract_to_dict(plan)
        output["route_decision"] = route_decision_to_dict(decision)
        print(json.dumps(output, ensure_ascii=False, indent=2))


def _handle_eval_prompts_command(args) -> None:
    """Evaluate prompt quality against golden planning cases."""
    _load_optional_dotenv()

    # Allow --provider to override env vars for convenience
    provider = getattr(args, "provider", None)
    if provider:
        for var in ("AAO_PLANNER_PROVIDER", "AAO_RISK_REVIEWER_PROVIDER",
                     "AAO_EXECUTION_PLANNER_PROVIDER"):
            if var not in os.environ:
                os.environ[var] = provider

    cases_path = args.cases
    if not Path(cases_path).is_absolute():
        cases_path = str(Path.cwd() / cases_path)

    summary = run_eval_cases(
        cases_path,
        mode=args.mode,
        repeat=args.repeat,
        verbose=getattr(args, "verbose", False),
    )

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        print(json.dumps(eval_summary_to_dict(summary), ensure_ascii=False, indent=2))
    else:
        print(render_eval_summary(summary))


def _prepare_approved_plan_for_command(
    args,
    decision,
    *,
    support_text_format: bool = False,
) -> PlanContract | None:
    """Planning Council gate for complex/orchestrated tasks.

    Returns an approved PlanContract if the plan passes verification AND the
    user has provided --approve.  Returns None if execution is blocked
    (verification failed or plan awaiting approval), after printing the
    relevant output.

    Phase 14.5: extracted from duplicate logic in _handle_ask_command and
    _handle_run_command.

    Phase 19: respects --planning-mode flag (deterministic or llm).
    """
    if not (decision.task_size == "large" and decision.run_mode in ("orchestrated", "controlled")):
        return None

    planning_mode: PlanningMode = getattr(args, "planning_mode", "deterministic")
    council = build_default_council(mode=planning_mode)
    plan = council.create_plan(
        args.query,
        task_size=decision.task_size,
        run_mode=decision.run_mode,
        risk_level=decision.risk_level,
        task_type=decision.task_type,
    )

    from .control_plane import ControlPlane
    cp = ControlPlane()
    verification = cp.verify_plan(plan)

    if not verification.passed:
        decision_dict = route_decision_to_dict(decision)
        decision_dict["plan"] = plan_contract_to_dict(plan)
        decision_dict["plan_verification"] = {
            "passed": verification.passed,
            "action": verification.action,
            "reason": verification.reason,
            "recovery_hint": verification.recovery_hint,
        }
        decision_dict["_note"] = "Plan verification failed — execution blocked."
        if support_text_format and getattr(args, "format", "json") == "text":
            print(render_plan_contract(plan))
            print(f"\nPlan verification FAILED: {verification.reason}")
        else:
            print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return None

    if not getattr(args, "approve", False):
        decision_dict = route_decision_to_dict(decision)
        decision_dict["plan"] = plan_contract_to_dict(plan)
        decision_dict["plan_verification"] = {
            "passed": True,
            "action": "needs_human_review",
            "reason": "Complex task requires plan approval",
        }
        decision_dict["_note"] = (
            "Plan is ready but needs approval. Use --approve to proceed, "
            "or use 'plan' command to review first."
        )
        if support_text_format and getattr(args, "format", "json") == "text":
            print(render_plan_contract(plan))
            print("\nPlan is ready. Use --approve to proceed with execution.")
        else:
            print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return None

    plan.approve()
    return plan


def _handle_ask_mainline(
    args,
    decision,
    plan: PlanContract | None,
    *,
    worker_mode: str = "fake",
    max_workers: int | None = None,
    execution_backend: str | None = None,
) -> None:
    """Execute the ask command through the mainline executor path.

    When *plan* is not None it was approved by the Planning Council gate.
    When *plan* is None the task was not large enough to trigger the gate,
    so we build a plan directly from the query.
    """
    if max_workers is None:
        max_workers = getattr(args, "max_workers", 2)
    if execution_backend is None:
        execution_backend = "native"
    executor = MainlineExecutor(Path.cwd())

    if plan is not None:
        result = executor.execute(plan, worker_mode=worker_mode,
                                  max_workers=max_workers,
                                  execution_backend=execution_backend)
    else:
        result = executor.execute_from_query(
            args.query,
            worker_mode=worker_mode,
            run_mode=decision.run_mode,
            task_size=decision.task_size,
            max_workers=max_workers,
            execution_backend=execution_backend,
        )

    output = result.to_dict()
    output["route_decision"] = route_decision_to_dict(decision)

    fmt = getattr(args, "format", "json")
    if fmt == "text":
        _print_mainline_result_text(result)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


def _print_mainline_result_text(result) -> None:
    """Print MainlineResult in human-readable text format."""
    sep = "=" * 64
    print(sep)
    print("AAO Mainline Execution Result")
    print(sep)
    print(f"  Status:       {result.status}")
    print(f"  Worker Mode:  {result.worker_mode}")
    print(f"  Run ID:       {result.run_id}")
    print(f"  Task ID:      {result.task_id}")
    print(f"  Plan ID:      {result.plan_id}")
    print()
    if result.evidence_status:
        es = result.evidence_status
        print("Evidence:")
        for item in es.get("items", []):
            marker = {"observed": "[OBSERVED]", "reported": "[REPORTED]", "missing": "[MISSING]"}.get(
                item["status"], "[?]"
            )
            print(f"  {marker} {item['key']}")
        print(f"  Changed files: {result.changed_files}")
    print()
    print("Control Decisions:")
    for d in result.control_decisions:
        status = "PASS" if d["passed"] else "BLOCK"
        print(f"  [{status}] {d['action']}: {d['reason']}")
    print()
    print(f"  Summary: {result.summary}")
    print()
    print("Artifacts:")
    print(f"  Report:   {result.report_path}")
    print(f"  Evidence: {result.evidence_path}")
    print(f"  Worker:   {result.worker_packet_path}")
    print(sep)


def _resolve_execution_path(
    decision,
    explicit_worker_mode: str | None = None,
    force_run: bool = False,
) -> tuple[str, str | None, str | None]:
    """Determine which execution path to take for an ask command.

    Returns ``(path, effective_worker_mode, execution_backend)`` where:

    *path* is one of:
      ``"mainline"`` — use MainlineExecutor
      ``"legacy"``  — use legacy Scheduler / YAML workflow
      ``"blocked"`` — execution blocked (missing dependency)
      ``"noop"``    — no execution (off / log mode)

    *execution_backend* is one of:
      ``"native"`` — MultiWorkerExecutor (ThreadPoolExecutor)
      ``"langgraph"`` — LangGraphRunner (checkpoint/resume/branching)
      ``None`` — not applicable (legacy/noop/blocked)
    """
    # Explicit --worker-mode always wins → mainline + native
    if explicit_worker_mode is not None:
        return ("mainline", explicit_worker_mode, "native")

    # Router says off/log → no execution (unless force_run)
    if should_only_log(decision) and not force_run:
        return ("noop", None, None)

    # controlled → mainline + native backend
    if decision.run_mode == "controlled":
        return ("mainline", "fake", "native")

    # orchestrated → mainline + langgraph backend
    if decision.run_mode == "orchestrated":
        from .runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if _LANGGRAPH_AVAILABLE:
            return ("mainline", "fake", "langgraph")
        elif force_run:
            print("Warning: LangGraph not installed. "
                  "Falling back to native backend (--force-run).")
            return ("mainline", "fake", "native")
        else:
            return ("blocked", None, None)

    # Everything else → legacy Scheduler / YAML workflow
    return ("legacy", None, None)


def _handle_ask_command(args) -> None:
    _load_optional_dotenv()
    project_root = Path.cwd()

    # Phase 9: route the task before workflow selection
    explicit_mode = getattr(args, "mode", None)
    decision = route_task(args.query, explicit_mode=explicit_mode)

    # P0.1: resolve execution path — explicit --worker-mode, router decision,
    # or legacy fallback
    worker_mode = getattr(args, "worker_mode", None)
    force_run = getattr(args, "force_run", False)
    path, effective_worker_mode, execution_backend = _resolve_execution_path(
        decision,
        explicit_worker_mode=worker_mode,
        force_run=force_run,
    )

    if path == "noop":
        decision_dict = route_decision_to_dict(decision)
        fmt = getattr(args, "format", "json")
        if fmt == "text":
            print(render_route_decision(decision))
        else:
            decision_dict["_note"] = "Route is log/off — no workflow executed. Use --force-run to run anyway."
            print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return

    if path == "blocked":
        decision_dict = route_decision_to_dict(decision)
        fmt = getattr(args, "format", "json")
        if fmt == "text":
            print(render_route_decision(decision))
            print("\nOrchestrated mode requires LangGraph, which is not installed.")
            print("Install with: pip install langgraph")
            print("Or use --force-run to fall back to native backend.")
        else:
            decision_dict["_note"] = (
                "Orchestrated mode requires LangGraph, which is not installed. "
                "Install with: pip install langgraph "
                "Or use --force-run to fall back to native backend."
            )
            print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return

    # Phase 13: Planning Council gate (for both mainline and legacy paths)
    plan = _prepare_approved_plan_for_command(args, decision, support_text_format=True)
    if plan is None and decision.task_size == "large" and decision.run_mode in ("orchestrated", "controlled"):
        return  # blocked by planning gate — message already printed

    if path == "mainline":
        _handle_ask_mainline(args, decision, plan, worker_mode=effective_worker_mode,
                             max_workers=getattr(args, "max_workers", None),
                             execution_backend=execution_backend)
        return

    llm_config = _parse_llm_config(args)
    if llm_config.get("global_provider"):
        os.environ["LLM_PROVIDER"] = llm_config["global_provider"]
    if llm_config.get("global_model"):
        os.environ["LLM_DEFAULT_MODEL"] = llm_config["global_model"]

    workflow_path, routing_reason = _resolve_workflow_for_ask(
        query=args.query,
        project_root=project_root,
        llm_config=llm_config,
    )
    workflow = load_workflow(workflow_path)

    llm_overrides = _build_scheduler_llm_overrides(llm_config)
    scheduler = Scheduler(
        workflow=workflow,
        project_root=project_root,
        llm_overrides=llm_overrides,
    )
    state, result = scheduler.run(query=args.query)

    # Record route decision in state
    state.record_route_decision(route_decision_to_dict(decision))

    preview = None
    if args.raw:
        payload = build_raw_payload(state=state, result=result, extra_preview=preview)
    else:
        payload = build_run_payload(
            query=args.query,
            workflow_name=str(workflow.get("name", workflow_path.stem)),
            state=state,
            result=result,
            project_root=project_root,
            extra_preview=preview,
            routing_reason=routing_reason,
            llm_overrides=llm_overrides,
        )
    fmt = getattr(args, "format", "json")
    if fmt == "text":
        print(format_run_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _handle_review_command(args) -> None:
    _load_optional_dotenv()
    project_root = Path.cwd()

    # ---- MainlineExecutor review path (Phase 18+) ----
    from .mainline_executor import MainlineExecutor

    mainline_review_path = project_root / "outputs" / "reviews" / f"{args.task_id}.json"
    if mainline_review_path.exists():
        result = MainlineExecutor.resume_from_review(
            args.task_id,
            decision=args.decision,
            reason=args.reason,
        )
        if result is None:
            print(f"Review task not found: {args.task_id}")
            return
        output = result.to_dict()
        fmt = getattr(args, "format", "json")
        if fmt == "text":
            _print_mainline_result_text(result)
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # ---- Legacy Scheduler review path ----
    state_path = project_root / "outputs" / "states" / f"{args.task_id}.json"
    if not state_path.exists():
        print(f"State not found for task: {args.task_id}")
        return

    workflow_path = _resolve_review_workflow_path(
        task_id=args.task_id,
        project_root=project_root,
        explicit_workflow=args.workflow,
    )
    workflow = load_workflow(workflow_path)
    state = StateCenter.load_from(state_path)
    scheduler = Scheduler(workflow=workflow, project_root=project_root)
    state, result = scheduler.resume_human_review(
        state=state,
        decision=args.decision,
        reason=args.reason,
    )
    if args.raw:
        payload = build_raw_payload(state=state, result=result)
    else:
        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name=str(workflow.get("name", workflow_path.stem)),
            state=state,
            result=result,
            project_root=project_root,
        )
    fmt = getattr(args, "format", "json")
    if fmt == "text":
        print(format_run_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


# Valid workflow names for LLM router
_VALID_WORKFLOW_NAMES = frozenset([
    "deep_research",
    "deep_research_supervised",
    "deep_research_human_review",
    "customer_support_brief",
])


def _route_workflow_with_llm(query: str, llm_client) -> str | None:
    """Use LLM to classify query and return workflow name.

    Returns None if LLM call fails or returns invalid value.
    """
    prompt = f"""Classify this task into one category. Return ONLY the category name, nothing else.

Categories:
- deep_research: research, analysis, investigation tasks
- customer_support_brief: customer service, tickets, support requests
- deep_research_human_review: tasks requiring human approval/confirmation
- deep_research_supervised: tasks requiring supervisor review

Task: {query}

Category:"""

    try:
        response = llm_client.complete(prompt, temperature=0.1, max_tokens=20)
        result = response.strip().lower()

        # Normalize: remove surrounding quotes/backticks
        if len(result) >= 2:
            if (result.startswith('"') and result.endswith('"')) or \
               (result.startswith("'") and result.endswith("'")) or \
               (result.startswith("`") and result.endswith("`")):
                result = result[1:-1]

        # Strict match: result must exactly equal a valid workflow name
        if result in _VALID_WORKFLOW_NAMES:
            return result
        return None
    except Exception:
        return None


def _resolve_workflow_for_ask(*, query: str, project_root: Path, llm_config: dict) -> tuple[Path, str]:
    """Resolve workflow path using explicit rules, LLM router, then fallback rules.

    Returns (workflow_path, routing_reason).

    Priority:
    1. Explicit rule-based intent (human review / supervisor / support)
    2. LLM router (if available)
    3. Rule-based default fallback
    """
    explicit_workflow = _infer_workflow_path(query=query, project_root=project_root, include_default=False)
    if explicit_workflow is not None:
        return explicit_workflow, _build_routing_reason(query, str(explicit_workflow.stem), source="keyword_match")

    # Try LLM router first
    from .llm_client import LLMClient

    try:
        provider_name = llm_config.get("global_provider") or os.environ.get("LLM_PROVIDER")
        model = llm_config.get("global_model") or os.environ.get("LLM_DEFAULT_MODEL")

        if provider_name:
            from .llm_providers import get_provider
            provider = get_provider(provider_name)
            llm_client = LLMClient(provider=provider, default_model=model)
        else:
            llm_client = LLMClient(default_model=model)

        # Skip mock provider for routing (use rules instead)
        if llm_client.provider_name != "mock":
            workflow_name = _route_workflow_with_llm(query, llm_client)
            if workflow_name in _VALID_WORKFLOW_NAMES:
                wf_path = (project_root / "workflows" / f"{workflow_name}.yaml").resolve()
                return wf_path, _build_routing_reason(query, workflow_name, source="llm_router")
    except Exception:
        pass  # Fall through to rule-based routing

    # Fallback to rule-based routing
    fallback_path = _infer_workflow_path(query=query, project_root=project_root)
    return fallback_path, _build_routing_reason(query, str(fallback_path.stem), source="fallback")


def _build_routing_reason(query: str, workflow_name: str, source: str) -> str:
    """Build a human-readable routing reason."""
    lowered = query.lower()
    if workflow_name == "deep_research_human_review":
        return "detected human-review intent in query"
    if workflow_name == "deep_research_supervised":
        return "detected supervisor-review intent in query"
    if workflow_name == "customer_support_brief":
        return "detected customer-support keywords in query"
    if source == "llm_router":
        return f"LLM classifier selected '{workflow_name}'"
    return "default research workflow"


def _infer_workflow_path(*, query: str, project_root: Path, include_default: bool = True) -> Path | None:
    """Infer the appropriate workflow based on query content.

    v1 uses simple keyword matching. Priority order:
    1. human_review - explicit human approval intent
    2. supervised - supervisor review intent
    3. support - customer support / ticket keywords
    4. research - default fallback
    """
    lowered = query.lower()

    # Human review: explicit intent for human approval
    human_review_keywords = [
        "human review",
        "human approval",
        "human confirmation",
        "human verify",
        "need human",
        "require human",
        "人工确认",
        "人工审核",
        "需要我确认",
        "需要人工",
        "人工拍板",
    ]
    if any(keyword in lowered for keyword in human_review_keywords):
        return (project_root / "workflows" / "deep_research_human_review.yaml").resolve()

    # Supervised: supervisor review intent
    supervised_keywords = [
        "supervisor review",
        "supervisor approval",
        "need review",
        "require review",
        "manager approval",
        "需要复核",
        "主管复核",
        "主管审核",
        "需要审核",
    ]
    if any(keyword in lowered for keyword in supervised_keywords):
        return (project_root / "workflows" / "deep_research_supervised.yaml").resolve()

    # Support: customer support / ticket keywords
    support_keywords = [
        "support",
        "customer support",
        "ticket",
        "reply plan",
        "shipment",
        "delayed shipment",
        "客服",
        "工单",
        "回复",
        "物流",
        "快递",
    ]
    if any(keyword in lowered for keyword in support_keywords):
        return (project_root / "workflows" / "customer_support_brief.yaml").resolve()

    if not include_default:
        return None

    # Default: research workflow
    return (project_root / "workflows" / "deep_research.yaml").resolve()


def _resolve_review_workflow_path(*, task_id: str, project_root: Path, explicit_workflow: str | None) -> Path:
    if explicit_workflow:
        return Path(explicit_workflow).resolve()

    report_path = project_root / "outputs" / "reports" / f"{task_id}.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found for task: {task_id}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    workflow_name = report.get("workflow_name")
    if not workflow_name:
        raise ValueError(f"workflow_name missing in report for task: {task_id}")

    workflow_path = project_root / "workflows" / f"{workflow_name}.yaml"
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
    return workflow_path.resolve()


def _handle_run_command(args) -> None:
    _load_optional_dotenv()

    # Phase 9/9A: route first, enforce mode semantics before touching files/LLM
    explicit_mode = getattr(args, "mode", None)
    decision = route_task(args.query, explicit_mode=explicit_mode)

    if should_only_log(decision) and not getattr(args, "force_run", False):
        decision_dict = route_decision_to_dict(decision)
        decision_dict["_note"] = "Route is log/off — no workflow executed. Use --force-run to run anyway."
        print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return

    if requires_future_runner(decision) and not getattr(args, "force_run", False):
        decision_dict = route_decision_to_dict(decision)
        decision_dict["_note"] = "Orchestrated mode requires LangGraph, which is not installed. Install with: pip install langgraph"
        print(json.dumps(decision_dict, ensure_ascii=False, indent=2))
        return

    # Phase 13: Planning Council gate
    plan = _prepare_approved_plan_for_command(args, decision, support_text_format=True)
    if plan is None and decision.task_size == "large" and decision.run_mode in ("orchestrated", "controlled"):
        return  # blocked by planning gate — message already printed

    workflow_path = Path(args.workflow).resolve()
    workflow = load_workflow(workflow_path)

    llm_config = _parse_llm_config(args)

    if llm_config.get("global_provider"):
        os.environ["LLM_PROVIDER"] = llm_config["global_provider"]
    if llm_config.get("global_model"):
        os.environ["LLM_DEFAULT_MODEL"] = llm_config["global_model"]

    llm_overrides = _build_scheduler_llm_overrides(llm_config)

    scheduler = Scheduler(
        workflow=workflow,
        project_root=workflow_path.parent.parent,
        llm_overrides=llm_overrides,
    )

    # Phase 15: orchestrated mode with LangGraph runner
    # Deprecation note: `run` command still uses the legacy Scheduler for
    # orchestrated tasks.  New code should use `ask --mode orchestrated`
    # which routes through MainlineExecutor → LangGraphRunner.
    if plan is not None and decision.run_mode == "orchestrated":
        from .runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if _LANGGRAPH_AVAILABLE:
            state, result = scheduler.run_orchestrated(
                plan=plan, query=args.query,
            )
        else:
            state, result = scheduler.run(query=args.query)
    else:
        state, result = scheduler.run(query=args.query)
    state.record_route_decision(route_decision_to_dict(decision))
    preview = None
    if args.raw:
        payload = build_raw_payload(state=state, result=result, extra_preview=preview)
    else:
        payload = build_run_payload(
            query=args.query,
            workflow_name=str(workflow.get("name", workflow_path.stem)),
            state=state,
            result=result,
            project_root=workflow_path.parent.parent,
            extra_preview=preview,
            llm_overrides=llm_overrides,
        )
    fmt = getattr(args, "format", "json")
    if fmt == "text":
        print(format_run_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_llm_config(args) -> dict:
    config = {
        "global_provider": getattr(args, "llm", None),
        "global_model": getattr(args, "model", None),
        "agent_llm": None,
    }

    agent_llm_str = getattr(args, "agent_llm", None)
    if agent_llm_str:
        agent_llm = {}
        for pair in agent_llm_str.split(","):
            if "=" not in pair:
                continue
            agent_name, llm_spec = pair.split("=", 1)
            agent_llm[agent_name.strip()] = llm_spec.strip()
        config["agent_llm"] = agent_llm if agent_llm else None

    return config


def _build_scheduler_llm_overrides(llm_config: dict) -> dict[str, dict[str, str | None]]:
    overrides: dict[str, dict[str, str | None]] = {}

    global_provider = llm_config.get("global_provider")
    global_model = llm_config.get("global_model")
    if global_provider or global_model:
        overrides["*"] = {"provider": global_provider, "model": global_model}

    agent_llm = llm_config.get("agent_llm") or {}
    for agent_name, spec in agent_llm.items():
        provider = spec
        model = None
        if ":" in spec:
            provider, model = spec.split(":", 1)
        overrides[agent_name] = {
            "provider": provider or None,
            "model": model or None,
        }

    return overrides


def _handle_agent_command(args) -> None:
    _load_optional_dotenv()
    try:
        agent_cls = get_agent(args.name)
    except KeyError:
        print(f"Error: Agent '{args.name}' not found.")
        print(f"Available agents: {', '.join(sorted(REGISTRY.keys()))}")
        return

    llm_provider = getattr(args, "llm", None)
    llm_model = getattr(args, "model", None)
    if llm_provider:
        from .llm_client import LLMClient
        from .llm_providers import get_provider

        try:
            provider = get_provider(llm_provider)
            agent = agent_cls(llm_client=LLMClient(provider=provider, default_model=llm_model))
        except Exception as exc:
            print(f"Error creating LLM provider '{llm_provider}': {exc}")
            print(f"Available providers: {', '.join(list_providers())}")
            return
    elif llm_model:
        from .llm_client import LLMClient

        agent = agent_cls(llm_client=LLMClient(default_model=llm_model))
    else:
        agent = agent_cls()

    state = StateCenter(query=args.query, max_steps=1)
    context_view = state.prepare_view(agent.config.reads)

    try:
        output = agent.run(context_view)
    except Exception as exc:
        print(f"Error running agent '{args.name}': {exc}")
        return

    if args.format == "json":
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        _print_agent_output_text(output)


def _print_agent_output_text(output: dict) -> None:
    for key, value in output.items():
        if isinstance(value, dict):
            print(f"\n{key}:")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, list):
                    print(f"  {sub_key}:")
                    for item in sub_value[:5]:
                        print(f"    - {item}")
                    if len(sub_value) > 5:
                        print(f"    ... and {len(sub_value) - 5} more")
                else:
                    print(f"  {sub_key}: {sub_value}")
        elif isinstance(value, list):
            print(f"\n{key}:")
            for item in value[:5]:
                print(f"  - {item}")
            if len(value) > 5:
                print(f"  ... and {len(value) - 5} more")
        else:
            print(f"\n{key}: {value}")


def _handle_agents_command(args) -> None:
    if not REGISTRY:
        print("No agents registered.")
        return

    if args.verbose:
        print("Available agents:\n")
        for name in sorted(REGISTRY.keys()):
            agent = REGISTRY[name]()
            config = agent.config
            print(f"  {name}:")
            print(f"    reads: {config.reads}")
            print(f"    writes: {[w.field for w in config.writes]}")
            print(f"    tools: {config.tools or 'none'}")
            print(f"    trust_level: {config.trust_level}")
            print()
    else:
        print("Available agents:")
        for name in sorted(REGISTRY.keys()):
            agent = REGISTRY[name]()
            writes = ", ".join(w.field for w in agent.config.writes)
            print(f"  {name} -> {writes}")


def _handle_providers_command(args) -> None:
    _load_optional_dotenv()
    providers = describe_providers()
    if not providers:
        print("No providers registered.")
        return

    if args.verbose:
        rows = [
            [
                provider.name,
                provider.mode,
                "yes" if provider.configured else "no",
                "yes" if provider.available else "no",
                provider.default_model,
                provider.api_base or "-",
                provider.note or "-",
            ]
            for provider in providers
        ]
        print(format_table(rows, ["Provider", "Mode", "Configured", "Available", "Default Model", "API Base", "Note"]))
        return

    rows = [
        [
            provider.name,
            provider.mode,
            "yes" if provider.configured else "no",
            provider.default_model,
        ]
        for provider in providers
    ]
    print(format_table(rows, ["Provider", "Mode", "Configured", "Default Model"]))


def _handle_project_context_command(args) -> None:
    project_root = Path.cwd()
    context = ProjectContext(project_root)

    if args.scan:
        context.scan()
        print(context.get_summary_text())
        return

    if args.file:
        summary = context.get_file_summary(args.file)
        if summary is None:
            print(f"File not found: {args.file}")
            return
        print(f"File: {summary.path}")
        print(f"Language: {summary.language}")
        print(f"Lines: {summary.line_count}, Characters: {summary.char_count}")
        print(f"Syntax errors: {summary.has_syntax_errors}")
        print()
        print("Preview:")
        print("-" * 40)
        print(summary.content_preview[:500])
        if len(summary.content_preview) > 500:
            print("... (truncated)")
        return

    if args.find:
        files = context.find_files(
            pattern=args.find,
            extension=args.extension,
            max_depth=args.max_depth,
        )
        if not files:
            print("No files found.")
            return
        print(f"Found {len(files)} files:\n")
        for file_info in files[:20]:
            type_str = "[DIR]" if file_info.is_directory else "[FILE]"
            print(f"  {type_str} {file_info.relative_path}")
        if len(files) > 20:
            print(f"\n... and {len(files) - 20} more")
        return

    structure = context.scan()
    print(f"Project: {structure.root_path}")
    print(f"Files: {structure.total_files}, Dirs: {structure.total_directories}")
    print(f"Size: {structure.total_size_bytes / 1024:.1f} KB")
    print("\nTop-level items:")
    for item in structure.top_level_items[:10]:
        type_str = "[DIR]" if item.is_directory else "[FILE]"
        print(f"  {type_str} {item.name}")



def _read_report_paths(project_root: Path, task_id: str) -> tuple[str | None, str | None]:
    """Extract report and evidence paths from the real report JSON structure.

    The report written by ConvergenceReportWriter is a top-level dict with
    ``artifact_summary.report_path`` — NOT ``{"result": {...}}``.
    Evidence path follows the conventional location.
    """
    report_file = project_root / "outputs" / "reports" / f"{task_id}.json"
    rp: str | None = None
    if report_file.exists():
        try:
            report_data = json.loads(report_file.read_text(encoding="utf-8"))
            artifacts = report_data.get("artifact_summary", {})
            if isinstance(artifacts, dict):
                raw = artifacts.get("report_path")
                rp = raw if isinstance(raw, str) else None
        except Exception:
            rp = None

    evidence_file = project_root / "outputs" / "evidence" / f"{task_id}.json"
    ep: str | None = str(evidence_file) if evidence_file.exists() else None

    return rp, ep


def _handle_status_command(args) -> None:
    """Show live run status for a task."""
    project_root = Path.cwd()
    state_path = project_root / "outputs" / "states" / f"{args.task_id}.json"
    if not state_path.exists():
        print(f"State not found for task: {args.task_id}")
        return

    state = StateCenter.load_from(state_path)

    rp, ep = _read_report_paths(project_root, args.task_id)
    workflow_total = getattr(state.metadata, "workflow_total", None)
    view = build_live_view(state, workflow_total=workflow_total, report_path=rp, evidence_path=ep)
    print(render_live_view(view))


def _handle_watch_command(args) -> None:
    """Watch run status — polls state file until terminal or --once."""
    import time as _time

    project_root = Path.cwd()
    state_path = project_root / "outputs" / "states" / f"{args.task_id}.json"

    if not state_path.exists():
        print(f"State not found for task: {args.task_id}")
        return

    while True:
        if not state_path.exists():
            print(f"State file disappeared for task: {args.task_id}")
            return

        try:
            state = StateCenter.load_from(state_path)
        except Exception:
            print(f"Failed to load state for task: {args.task_id}")
            return

        rp, ep = _read_report_paths(project_root, args.task_id)
        workflow_total = getattr(state.metadata, "workflow_total", None)
        view = build_live_view(state, workflow_total=workflow_total, report_path=rp, evidence_path=ep)
        print(render_live_view(view))

        status = state.metadata.status
        if is_terminal(status) or args.once:
            if not is_terminal(status) and args.once:
                print("(run is still in progress; use watch without --once to keep watching)")
            return

        _time.sleep(max(0.1, args.interval))


def _handle_worker_command(args) -> None:
    """Handle worker create/inspect commands."""
    from .worker_protocol import (
        WorkerTaskPacket,
        classify_worker_evidence,
        load_manifest,
        list_observed_files,
        load_worker_result_text,
        load_worker_status,
    )

    if args.worker_command == "create":
        packet = WorkerTaskPacket.create(
            project_root=".",
            run_id=args.run_id,
            task_id=args.task_id,
            title=args.title or "",
            objective=args.objective,
            allowed_files=args.allowed,
            denied_files=args.denied,
            protected_files=args.protected,
            required_checks=args.checks,
            expected_evidence=args.evidence,
            risk_level=args.risk,
            run_mode=args.mode,
        )
        packet_dir = packet.write()
        print(json.dumps({
            "status": "created",
            "packet_dir": str(packet_dir),
            "run_id": packet.run_id,
            "task_id": packet.task_id,
            "title": packet.title,
            "objective": packet.objective,
            "files": [
                "manifest.json",
                "task.md",
                "constraints.md",
                "expected_evidence.md",
            ],
        }, ensure_ascii=False, indent=2))

    elif args.worker_command == "inspect":
        packet_path = Path(args.path).resolve()
        if not packet_path.is_dir():
            print(json.dumps({"status": "error", "reason": f"Not a directory: {packet_path}"}, ensure_ascii=False, indent=2))
            return

        manifest = load_manifest(packet_path)
        status_data = load_worker_status(packet_path)
        result_text = load_worker_result_text(packet_path)
        observed = list_observed_files(packet_path)

        expected = manifest.get("expected_evidence", [])
        evidence_status = classify_worker_evidence(
            packet_path=packet_path,
            expected_evidence=expected,
            worker_kind=manifest.get("worker_kind", "claude_code"),
            denied_files=manifest.get("denied_files", []),
        )

        print(json.dumps({
            "packet_dir": str(packet_path),
            "manifest": manifest,
            "worker_status": status_data.get("status", "unknown"),
            "result_summary": result_text[:300] if result_text else "",
            "observed_files": observed,
            "evidence_items": [
                {"key": i.key, "status": i.status, "path": i.path, "description": i.description}
                for i in evidence_status.items
            ],
            "has_missing_required": evidence_status.has_missing_required,
            "is_malformed": evidence_status.is_malformed,
            "changed_files": evidence_status.changed_files,
            "denied_files_changed": evidence_status.denied_files_changed,
        }, ensure_ascii=False, indent=2))


# =============================================================================
# Phase 24 — Project Session CLI handlers
# =============================================================================


def _resolve_project_id(store: ProjectSessionStore, explicit: str | None = None) -> tuple[str | None, str | None]:
    """Return ``(project_id, error_reason)``.

    *project_id* is the resolved ID, or None when no suitable project is found.
    *error_reason* is non-None only when *project_id* is None, indicating WHY:
      ``"explicit_not_found"`` — the caller passed an explicit ID that doesn't exist
      ``"no_active"`` — no explicit ID and no active sessions
    """
    if explicit:
        session = store.load_session(explicit)
        if session is None:
            return None, "explicit_not_found"
        return explicit, None

    sessions = store.list_sessions()
    active = [s for s in sessions if s.get("status") == "active"]
    if not active:
        return None, "no_active"
    return active[0]["project_id"], None


def _print_missing_project_error(reason: str | None, explicit_id: str | None) -> None:
    """Print a context-appropriate error when no project is found."""
    if reason == "explicit_not_found":
        print(json.dumps({
            "error": f"Project not found: {explicit_id}",
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({
            "error": "No active project session. Use 'project start <goal>' to create one.",
        }, ensure_ascii=False, indent=2))


def _handle_project_command(args) -> None:
    _load_optional_dotenv()
    store = ProjectSessionStore(Path.cwd())

    if args.project_command == "start":
        _handle_project_start(args, store)
    elif args.project_command == "status":
        _handle_project_status(args, store)
    elif args.project_command == "ask":
        _handle_project_ask(args, store)
    elif args.project_command == "continue":
        _handle_project_continue(args, store)
    elif args.project_command == "close":
        _handle_project_close(args, store)
    elif args.project_command == "approve":
        _handle_project_approve(args, store)
    elif args.project_command == "reject":
        _handle_project_reject(args, store)
    elif args.project_command == "request-changes":
        _handle_project_request_changes(args, store)
    elif args.project_command == "self-check":
        _handle_project_self_check(args, store)


def _handle_project_start(args, store: ProjectSessionStore) -> None:
    """Create a new project session and optionally generate a plan."""
    session = store.create_session(
        goal=args.goal,
        project_id=getattr(args, "project_id", None) or None,
    )

    # Generate a plan via Planning Council
    planning_mode: PlanningMode = getattr(args, "planning_mode", "deterministic")
    council = build_default_council(mode=planning_mode)
    plan = council.create_plan(
        args.goal,
        task_size="large",
        run_mode="orchestrated",
        risk_level="medium",
        task_type="project",
    )

    # Convert plan steps (list[str]) to milestones
    milestones: list[ProjectMilestone] = []
    for i, step_text in enumerate(plan.steps):
        m = ProjectMilestone(
            milestone_id=_new_id(),
            name=step_text if len(step_text) <= 80 else step_text[:77] + "...",
            description=step_text,
            plan_step_ids=[f"step-{i + 1}"],
            approval_required=True,
        )
        milestones.append(m)

    if milestones:
        milestones[0].status = "in_progress"
        session.current_milestone = milestones[0].milestone_id

    store.save_milestones(session.project_id, milestones)
    session.next_recommended_action = (
        f"Review and approve milestone: {milestones[0].name}"
        if milestones else "No milestones yet"
    )
    store.save_session(session)

    # Log the creation decision
    store.log_decision(session.project_id, DecisionLog(
        entry_id=_new_id(),
        timestamp=_now(),
        decision=f"Project created: {args.goal}",
        reason="User initiated project session",
        made_by="human",
    ))

    print(json.dumps({
        "project_id": session.project_id,
        "goal": session.goal,
        "status": session.status,
        "milestones": [m.to_dict() for m in milestones],
        "next": session.next_recommended_action,
    }, ensure_ascii=False, indent=2))


def _handle_project_status(args, store: ProjectSessionStore) -> None:
    """Show current project status."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    session = store.load_session(pid)
    milestones = store.load_milestones(pid)
    decisions = store.load_decisions(pid, limit=10)
    approvals = store.load_approvals(pid)

    # Determine current milestone detail
    current_ms = None
    for m in milestones:
        if m.milestone_id == session.current_milestone:
            current_ms = m.to_dict()
            break

    pending_approvals = [
        a.to_dict() for a in approvals if a.status == "awaiting_approval"
    ]

    output = {
        "project_id": session.project_id,
        "goal": session.goal,
        "status": session.status,
        "created_at": session.created_at,
        "last_active_at": session.last_active_at,
        "current_milestone": current_ms,
        "completed_milestones": session.completed_milestones,
        "pending_decisions": session.pending_decisions,
        "pending_approvals": pending_approvals,
        "open_risks": session.open_risks,
        "recent_decisions": [d.to_dict() for d in decisions[:5]],
        "next_recommended_action": session.next_recommended_action,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _read_evidence_json(path_str: str, *, root: Path | None = None) -> dict | None:
    """Try to read a JSON evidence file, returning None on any failure.

    If *path_str* is relative and *root* is given, resolve against *root*.
    """
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute() and root is not None:
        p = root / p
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _evidence_label(evidence_dict: dict | None, key: str) -> str:
    """Return ``[observed]`` or ``[reported]`` for an evidence key.

    Looks up *key* in the evidence_status items written by the evidence
    classifier.  Returns ``[reported]`` when the classification is not
    available (default: trust nothing without classifier confirmation).
    """
    if evidence_dict is None:
        return "[reported]"
    items = evidence_dict.get("evidence_status", {}).get("items", [])
    for item in items:
        if isinstance(item, dict) and item.get("key") == key:
            return f"[{item['status']}]"
    return "[reported]"


def _search_decisions(
    question: str, decisions: list[DecisionLog]
) -> list[DecisionLog]:
    """Return decisions ordered by keyword overlap with *question*.

    Simple bag-of-words overlap: more shared words → higher score.
    Decisions with zero overlap are dropped.
    """
    q_words = set(question.lower().split())
    if not q_words:
        return list(decisions)
    scored = []
    for d in decisions:
        d_text = f"{d.decision} {d.reason} {' '.join(d.alternatives)}".lower()
        d_words = set(d_text.split())
        overlap = len(q_words & d_words)
        if overlap > 0:
            scored.append((overlap, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored]


def _handle_project_ask(args, store: ProjectSessionStore) -> None:
    """Answer a question based on recorded project artifacts.

    Reads real evidence files (test output, changed files, reviewer
    findings, audit reports) referenced by run links.  Falls back to
    honest "I don't know" when artifacts are missing.
    """
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    ctx = store.build_context(pid)
    if ctx is None:
        # Session was deleted between _resolve_project_id and build_context
        # (TOCTOU race — practically won't happen, but guard anyway).
        _print_missing_project_error("explicit_not_found", pid)
        return

    question = args.question
    question_lower = question.lower()
    answer = ""
    evidence: list[str] = []

    # ---- Design / why questions: search all decisions ----
    if any(kw in question_lower for kw in ("why", "选择", "方案", "choose", "design", "设计")):
        matched = _search_decisions(question, ctx.recent_decisions)
        # Fall back to most recent decision if no keyword match
        if not matched and ctx.recent_decisions:
            matched = [ctx.recent_decisions[0]]
        if matched:
            d = matched[0]
            answer = f"Decision: {d.decision}. Reason: {d.reason}."
            if d.alternatives:
                answer += f" Alternatives considered: {', '.join(d.alternatives)}."
            evidence.append(f"DecisionLog entry {d.entry_id} ({d.timestamp})")
            if len(matched) > 1:
                answer += f" ({len(matched) - 1} more matching decision(s) found.)"
        else:
            answer = "I have no record of design decisions matching this question."
            evidence.append("DecisionLog is empty — no decisions recorded yet")

    # ---- File changes: read evidence from run links ----
    elif any(kw in question_lower for kw in ("改了什么", "changed", "file", "文件")):
        ms = ctx.current_milestone
        if ms:
            answer = f"Current milestone '{ms.name}' covers step(s): {', '.join(ms.plan_step_ids)}."
            evidence.append(f"Milestone {ms.milestone_id}")
        run_links = store.load_run_links(pid)
        changed_seen: set[str] = set()
        obs_label = "[reported]"
        for link in run_links:
            ev = _read_evidence_json(link.evidence_path, root=store._root)
            if ev:
                cf = ev.get("changed_files", [])
                if isinstance(cf, list):
                    changed_seen.update(str(f) for f in cf)
                obs_label = _evidence_label(ev, "changed_files")
        if changed_seen:
            answer += f" Files changed across runs ({obs_label}): {', '.join(sorted(changed_seen))}."
            evidence.extend(
                link.evidence_path for link in run_links if link.evidence_path
            )
        elif not answer:
            answer = "No file-change records available. Run links are empty."
        else:
            answer += " No changed-files detail in run evidence."

    # ---- Test results: read test output from evidence ----
    elif any(kw in question_lower for kw in ("test", "测试", "结果")):
        run_links = store.load_run_links(pid)
        found = False
        for link in run_links:
            ev = _read_evidence_json(link.evidence_path, root=store._root)
            if ev:
                test_out = ev.get("test_output", "")
                if test_out:
                    label = _evidence_label(ev, "test_output")
                    snippet = test_out[:500]
                    answer = f"Test output from {link.run_id} ({label}): {snippet}"
                    evidence.append(link.evidence_path)
                    found = True
                    break
        if not found:
            answer = "No test output found in run evidence."
            if run_links:
                evidence.extend(link.evidence_path for link in run_links if link.evidence_path)
            else:
                evidence.append("run_links.jsonl is empty")

    # ---- Reviewer findings: read from evidence ----
    elif any(kw in question_lower for kw in ("reviewer", "审查", "发现", "finding")):
        run_links = store.load_run_links(pid)
        findings_found = False
        for link in run_links:
            ev = _read_evidence_json(link.evidence_path, root=store._root)
            if ev:
                rf = ev.get("review_findings", [])
                if rf:
                    findings_found = True
                    label = _evidence_label(ev, "review_findings")
                    if isinstance(rf, list) and len(rf) > 0:
                        item = rf[0]
                        if isinstance(item, dict):
                            answer = (
                                f"Reviewer finding in {link.run_id} ({label}): "
                                f"[{item.get('severity', '?')}] {item.get('description', str(item))}"
                            )
                        else:
                            answer = f"Reviewer findings in {link.run_id} ({label}): {len(rf)} finding(s)."
                    evidence.append(link.evidence_path)
                    break
        if not findings_found:
            answer = "No reviewer findings recorded in run evidence."
            evidence.append("Run evidence paths in run_links.jsonl")

    # ---- Repair history: read audit reports from run links ----
    elif any(kw in question_lower for kw in ("修了几轮", "repair", "修复", "修了")):
        run_links = store.load_run_links(pid)
        repair_info: list[str] = []
        audit_label = "[reported]"
        for link in run_links:
            if link.audit_path:
                audit = _read_evidence_json(link.audit_path, root=store._root)
                if audit:
                    rounds = audit.get("repair_rounds", audit.get("total_rounds", None))
                    if rounds is not None:
                        repair_info.append(f"{link.run_id}: {rounds} round(s)")
                        evidence.append(link.audit_path)
                        audit_label = _evidence_label(audit, "repair_rounds")
        if repair_info:
            answer = f"Repair history ({audit_label}): {'; '.join(repair_info)}."
        else:
            answer = "No repair history available — no audit reports with repair data found."
            evidence.extend(
                link.audit_path for link in run_links if link.audit_path
            )

    # ---- Risks ----
    elif any(kw in question_lower for kw in ("风险", "risk")):
        if ctx.open_risks:
            answer = f"Open risks: {'; '.join(ctx.open_risks)}"
        else:
            answer = "No open risks recorded."
        evidence.append("session.open_risks")

    # ---- Next step ----
    elif any(kw in question_lower for kw in ("下一步", "next", "接下来")):
        s = store.load_session(pid)
        answer = (s.next_recommended_action if s else None) or "No recommended action recorded."
        evidence.append("session.next_recommended_action")

    # ---- Unknown ----
    else:
        # Build targeted artifact suggestions based on question keywords.
        # These keywords must NOT overlap with the known-branch keywords above
        # so that only genuinely unhandled questions reach this path.
        suggested_paths: list[str] = []
        if any(kw in question_lower for kw in ("history", "记录", "log", "decision", "choice", "选择")):
            suggested_paths.append(f"  - .aao/sessions/{pid}/decision_log.jsonl (design decisions)")
        if any(kw in question_lower for kw in ("progress", "status", "state", "进度", "状态")):
            suggested_paths.append(f"  - .aao/sessions/{pid}/milestones.json (milestone state)")
        if any(kw in question_lower for kw in ("execution", "执行", "timeline", "时间线")):
            suggested_paths.append(f"  - .aao/sessions/{pid}/run_links.jsonl (execution runs)")
        if any(kw in question_lower for kw in ("approval", "approve", "pending", "审批", "待审批")):
            suggested_paths.append(f"  - .aao/sessions/{pid}/session.json (approval state)")
        if not suggested_paths:
            suggested_paths = [
                f"  - .aao/sessions/{pid}/decision_log.jsonl (design decisions)",
                f"  - .aao/sessions/{pid}/run_links.jsonl (execution runs)",
                f"  - .aao/sessions/{pid}/milestones.json (milestone state)",
                f"  - .aao/sessions/{pid}/session.json (project state)",
            ]
        answer = (
            f"No recorded information found for this question. "
            f"Suggest checking these artifact paths:\n"
            + "\n".join(suggested_paths) +
            f"\nTo make this answerable in the future, ensure the relevant "
            f"phase records this data in DecisionLog, evidence artifacts, "
            f"or milestone summaries."
        )
        evidence.append(f".aao/sessions/{pid}/decision_log.jsonl")
        evidence.append(f".aao/sessions/{pid}/run_links.jsonl")

    print(json.dumps({
        "question": question,
        "answer": answer,
        "evidence": evidence,
    }, ensure_ascii=False, indent=2))


def _handle_project_continue(args, store: ProjectSessionStore) -> None:
    """Resume the current project — rebuild plan, execute the current milestone.

    Loads session state, finds the current in-progress milestone, builds a
    PlanContract from remaining milestones, dispatches execution via
    MainlineExecutor, and links the resulting run.
    """
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    session = store.load_session(pid)
    if session is None:
        return

    if session.status == "completed":
        print(json.dumps({
            "error": "Project is completed. Cannot continue a closed project.",
            "project_id": pid,
        }, ensure_ascii=False, indent=2))
        return

    # Check if milestone is awaiting approval (Phase 25 gate)
    ms = store.get_current_milestone(pid)
    if ms and ms.status == "paused_for_approval":
        print(json.dumps({
            "project_id": pid,
            "status": "paused_for_approval",
            "current_milestone": ms.to_dict(),
            "_note": (
                "Milestone is waiting for approval. Use 'project approve', "
                "'project reject', or 'project request-changes' to proceed."
            ),
        }, ensure_ascii=False, indent=2))
        return

    session.status = "active"
    store.save_session(session)

    # Build a PlanContract from remaining milestones and execute
    if ms is None:
        print(json.dumps({
            "error": "No current milestone to execute.",
            "project_id": pid,
            "status": session.status,
            "_hint": "All milestones may be complete. Check 'project status' for details.",
        }, ensure_ascii=False, indent=2))
        return

    # Construct a plan from session state
    milestones = store.load_milestones(pid)
    remaining = [m for m in milestones if m.status != "completed"]

    from .planning import PlanContract
    plan = PlanContract(
        plan_id=f"resume-{pid}",
        objective=f"{session.goal} — {ms.name}",
        task_size="medium",
        planning_mode="deterministic",
        steps=[m.description for m in remaining],
        risks=session.open_risks,
    )
    plan.approve()  # resume plan is pre-approved — derived from existing milestones

    # Execute via MainlineExecutor
    executor = MainlineExecutor(Path.cwd())
    result = executor.execute(plan, worker_mode="fake")

    # Link the run to the current milestone
    run_link = ProjectRunLink(
        milestone_id=ms.milestone_id,
        run_id=result.run_id,
        evidence_path=result.evidence_path or "",
        audit_path=result.report_path or "",
        status=result.status,
    )
    store.link_run(pid, run_link)

    # If execution succeeded, submit for human approval (Phase 25 gate)
    if result.status == "completed":
        # Collect evidence from run artifacts
        evidence_data = _read_evidence_json(result.evidence_path, root=store._root) or {}

        store.submit_for_approval(
            pid,
            ms.milestone_id,
            evidence_summary=result.summary or "",
            files_changed=list(result.changed_files),
            test_results_summary=evidence_data.get("test_output", ""),
            reviewer_findings=[
                f.get("description", str(f)) if isinstance(f, dict) else str(f)
                for f in result.review_findings
            ],
            repair_history=[
                str(r.get("round", r)) if isinstance(r, dict) else str(r)
                for r in result.repair_rounds
            ],
            open_risks=list(session.open_risks),
        )
        # session was mutated on disk by submit_for_approval — reload is
        # mandatory before any further use of the session object below.
        session = store.load_session(pid)
        if session is None:
            return

    # Log the decision
    store.log_decision(pid, DecisionLog(
        entry_id=_new_id(),
        timestamp=_now(),
        decision=f"Resumed execution of milestone: {ms.name}",
        reason=f"Project continue — status: {result.status}",
        made_by="control_plane",
        evidence_refs=[result.evidence_path or "", result.report_path or ""],
    ))

    # Refresh milestone state
    ms = store.get_current_milestone(pid)

    # Resume summary: last decision and pending approvals
    recent_decisions = store.load_decisions(pid, limit=1)
    last_decision = recent_decisions[0].to_dict() if recent_decisions else None
    approvals = store.load_approvals(pid)
    pending_approvals = [
        a.to_dict() for a in approvals if a.status == "awaiting_approval"
    ]

    output = {
        "project_id": pid,
        "goal": session.goal,
        "status": session.status,
        "run_id": result.run_id,
        "run_status": result.status,
        "current_milestone": ms.to_dict() if ms else None,
        "completed_milestones": session.completed_milestones,
        "last_decision": last_decision,
        "pending_approvals": pending_approvals,
        "next_recommended_action": session.next_recommended_action,
        "_note": (
            "Milestone execution finished. Awaiting human approval — use "
            "'project approve/reject/request-changes' to continue."
            if result.status == "completed"
            else f"Milestone execution finished with status: {result.status}."
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _handle_project_close(args, store: ProjectSessionStore) -> None:
    """Close the current project."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    session = store.close_session(pid)
    if session is None:
        return

    print(json.dumps({
        "project_id": pid,
        "status": "completed",
        "_note": "Project closed. Use 'project continue' to resume is no longer possible.",
    }, ensure_ascii=False, indent=2))


def _handle_project_approve(args, store: ProjectSessionStore) -> None:
    """Approve a milestone — unlocks the next one."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    approval = store.approve_milestone(pid, args.milestone_id)
    if approval is None:
        print(json.dumps({
            "error": f"No awaiting approval record found for milestone: {args.milestone_id}",
            "project_id": pid,
        }, ensure_ascii=False, indent=2))
        return

    session = store.load_session(pid)
    ms = store.get_current_milestone(pid)
    print(json.dumps({
        "project_id": pid,
        "milestone_id": args.milestone_id,
        "status": "approved",
        "approved_by": "human",
        "approved_at": approval.approved_at,
        "next_milestone": ms.to_dict() if ms else None,
        "next_recommended_action": session.next_recommended_action if session else None,
    }, ensure_ascii=False, indent=2))


def _handle_project_reject(args, store: ProjectSessionStore) -> None:
    """Reject a milestone — generates a need for re-planning."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    approval = store.reject_milestone(pid, args.milestone_id, reason=args.reason)
    if approval is None:
        print(json.dumps({
            "error": f"No awaiting approval record found for milestone: {args.milestone_id}",
            "project_id": pid,
        }, ensure_ascii=False, indent=2))
        return

    session = store.load_session(pid)
    print(json.dumps({
        "project_id": pid,
        "milestone_id": args.milestone_id,
        "status": "rejected",
        "reason": approval.rejection_reason,
        "rejected_at": approval.approved_at,
        "next_recommended_action": session.next_recommended_action if session else None,
    }, ensure_ascii=False, indent=2))


def _handle_project_request_changes(args, store: ProjectSessionStore) -> None:
    """Request changes to a milestone — enters repair path."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    approval = store.request_changes_milestone(pid, args.milestone_id, notes=args.notes)
    if approval is None:
        print(json.dumps({
            "error": f"No awaiting approval record found for milestone: {args.milestone_id}",
            "project_id": pid,
        }, ensure_ascii=False, indent=2))
        return

    session = store.load_session(pid)
    print(json.dumps({
        "project_id": pid,
        "milestone_id": args.milestone_id,
        "status": "changes_requested",
        "notes": approval.changes_requested_notes,
        "requested_at": approval.approved_at,
        "next_recommended_action": session.next_recommended_action if session else None,
    }, ensure_ascii=False, indent=2))


def _handle_project_self_check(args, store: ProjectSessionStore) -> None:
    """Run AAO self-check against a project session (Phase 27)."""
    pid, reason = _resolve_project_id(store, getattr(args, "project_id", None))
    if pid is None:
        _print_missing_project_error(reason, getattr(args, "project_id", None))
        return

    from .self_check import generate_repair_proposal, run_self_check

    category = getattr(args, "category", None)
    findings = run_self_check(store, pid, category=category)

    # Generate repair proposals where possible (blocked for protected paths)
    proposals: list[dict] = []
    blocked_count = 0
    for f in findings:
        proposal = generate_repair_proposal(f)
        if proposal is not None:
            proposals.append(proposal.to_dict())
        else:
            blocked_count += 1
        # Record finding in session
        store.record_system_issue(pid, f, proposal)

    session = store.load_session(pid)

    output = {
        "project_id": pid,
        "findings": [f.to_dict() for f in findings],
        "proposals": proposals,
        "blocked_proposals": blocked_count,
        "status": session.status if session else "unknown",
        "_note": (
            f"{len(findings)} system issue(s) detected."
            if findings
            else "No system issues detected."
        ),
    }
    if blocked_count:
        output["_note"] += (
            f" {blocked_count} repair proposal(s) blocked — "
            "they target AAO core files. Manual developer review required."
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
