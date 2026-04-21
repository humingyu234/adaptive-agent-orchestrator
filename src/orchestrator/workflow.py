from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local fallback path
    yaml = None


def load_workflow(path: str | Path) -> dict:
    workflow_path = Path(path)
    text = workflow_path.read_text(encoding="utf-8").lstrip("\ufeff")
    if yaml is not None:
        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict) and loaded.get("name"):
            return loaded
        parsed = _parse_simple_workflow(text)
        if isinstance(loaded, dict):
            merged = dict(loaded)
            if parsed.get("name") and not merged.get("name"):
                merged["name"] = parsed["name"]
            if parsed.get("max_steps") and not merged.get("max_steps"):
                merged["max_steps"] = parsed["max_steps"]
            return merged
        return parsed
    return _parse_simple_workflow(text)


def _parse_simple_workflow(text: str) -> dict:
    workflow: dict = {"agents": []}
    current_agent: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip().lstrip("\ufeff")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("name:") and not workflow.get("name"):
            workflow["name"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("max_steps:"):
            workflow["max_steps"] = int(stripped.split(":", 1)[1].strip())
            continue
        if stripped == "agents:":
            continue
        if stripped.startswith("- name:"):
            if current_agent is not None:
                workflow["agents"].append(current_agent)
            current_agent = {"name": stripped.split(":", 1)[1].strip()}
            continue
        if current_agent is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_agent[key.strip()] = _normalize_value(value.strip())

    if current_agent is not None:
        workflow["agents"].append(current_agent)
    return workflow


def _normalize_value(value: str):
    if value == "null":
        return None
    if value.isdigit():
        return int(value)
    return value
