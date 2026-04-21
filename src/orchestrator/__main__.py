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
from .llm_providers import describe_providers, list_providers
from .project_context import ProjectContext
from .regression_compare import RegressionCompare, RegressionSignal, format_regression_report
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

    review_parser = subparsers.add_parser("review", help="Approve or reject a paused human review task")
    review_parser.add_argument("--task-id", required=True, help="Task ID waiting for human review")
    review_parser.add_argument("--decision", required=True, choices=["approve", "reject"], help="Human review decision")
    review_parser.add_argument("--reason", default="", help="Optional human review reason")
    review_parser.add_argument("--workflow", help="Optional workflow path override")

    run_parser = subparsers.add_parser("run", help="Run a workflow against a query")
    run_parser.add_argument("--workflow", required=True, help="Path to workflow yaml")
    run_parser.add_argument("--query", required=True, help="Task query to execute")
    run_parser.add_argument("--llm", help="LLM provider to use (glm/openai/anthropic/codex/deepseek/ollama)")
    run_parser.add_argument("--model", help="Model name to use")
    run_parser.add_argument("--agent-llm", help="Per-agent LLM config, format: agent=provider:model")

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

    args = parser.parse_args()

    if args.command == "ask":
        _handle_ask_command(args)
    elif args.command == "review":
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


def _handle_ask_command(args) -> None:
    _load_optional_dotenv()
    project_root = Path.cwd()

    llm_config = _parse_llm_config(args)
    if llm_config.get("global_provider"):
        os.environ["LLM_PROVIDER"] = llm_config["global_provider"]
    if llm_config.get("global_model"):
        os.environ["LLM_DEFAULT_MODEL"] = llm_config["global_model"]

    workflow_path = _resolve_workflow_for_ask(
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
    print(json.dumps({"result": result.model_dump(), "state": state.metadata.to_dict()}, ensure_ascii=False, indent=2))


def _handle_review_command(args) -> None:
    _load_optional_dotenv()
    project_root = Path.cwd()
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
    print(json.dumps({"result": result.model_dump(), "state": state.metadata.to_dict()}, ensure_ascii=False, indent=2))


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


def _resolve_workflow_for_ask(*, query: str, project_root: Path, llm_config: dict) -> Path:
    """Resolve workflow path using LLM router with fallback to rules.

    Priority:
    1. LLM router (if available)
    2. Rule-based fallback (_infer_workflow_path)
    """
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
                return (project_root / "workflows" / f"{workflow_name}.yaml").resolve()
    except Exception:
        pass  # Fall through to rule-based routing

    # Fallback to rule-based routing
    return _infer_workflow_path(query=query, project_root=project_root)


def _infer_workflow_path(*, query: str, project_root: Path) -> Path:
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
    state, result = scheduler.run(query=args.query)
    print(json.dumps({"result": result.model_dump(), "state": state.metadata.to_dict()}, ensure_ascii=False, indent=2))


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


if __name__ == "__main__":
    main()
