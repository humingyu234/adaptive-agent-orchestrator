"""Declarative control policy — file rules, tool risk, human review triggers.

Loads from YAML or a plain dict.  Missing sections inherit safe defaults:
everything allowed, nothing protected, no human review required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Policy:
    """Declarative policy for a single AAO run or project.

    All fields have safe defaults — an empty policy blocks nothing.
    """

    mode: str = "controlled"
    allowed_files: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    human_review_required_for: list[str] = field(default_factory=list)
    tool_risk_levels: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # factories
    # ------------------------------------------------------------------

    @classmethod
    def defaults(cls) -> "Policy":
        """Return a permissive policy that blocks nothing."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        """Build a Policy from a plain dictionary (safe on missing keys)."""
        files_section = data.get("files") or {}
        checks_section = data.get("checks") or {}
        human_section = data.get("human_review") or {}
        tools_section = data.get("tools") or {}

        return cls(
            mode=data.get("mode", "controlled"),
            allowed_files=_as_str_list(files_section.get("allowed")),
            protected_files=_as_str_list(files_section.get("protected")),
            required_checks=_as_str_list(checks_section.get("required")),
            human_review_required_for=_as_str_list(human_section.get("required_for")),
            tool_risk_levels=_normalise_tool_risk_levels(tools_section),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Policy":
        """Load policy from a YAML file."""
        import yaml  # optional — only imported when this method is called

        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Policy YAML must be a mapping, got {type(raw).__name__}")
        return cls.from_dict(raw)

    # ------------------------------------------------------------------
    # file checks
    # ------------------------------------------------------------------

    def is_file_allowed(self, path: str) -> bool:
        """Return True if *path* matches at least one allowed-file pattern.

        An empty ``allowed_files`` list means *everything* is allowed.
        """
        if not self.allowed_files:
            return True
        return any(_match_glob(path, pattern) for pattern in self.allowed_files)

    def is_file_protected(self, path: str) -> bool:
        """Return True if *path* matches a protected-file pattern."""
        if not self.protected_files:
            return False
        return any(_match_glob(path, pattern) for pattern in self.protected_files)

    # ------------------------------------------------------------------
    # tool risk
    # ------------------------------------------------------------------

    def get_tool_risk_level(self, tool_name: str) -> str:
        """Return the declared risk level for *tool_name* (``"low"`` if unknown)."""
        return self.tool_risk_levels.get(tool_name, "low")

    # ------------------------------------------------------------------
    # human-review triggers
    # ------------------------------------------------------------------

    def requires_human_review_for_tool(self, tool_name: str) -> bool:
        """True when using a high-risk tool triggers human review."""
        if "high_risk_tool" not in self.human_review_required_for:
            return False
        return self.get_tool_risk_level(tool_name) == "high"

    def requires_human_review_for_file(self, path: str) -> bool:
        """True when touching a protected file triggers human review."""
        if "protected_file_change" not in self.human_review_required_for:
            return False
        return self.is_file_protected(path)

    def requires_human_review_for_test_failure(self) -> bool:
        """True when failed tests should trigger human review."""
        return "failed_tests" in self.human_review_required_for

    # ------------------------------------------------------------------
    # required checks
    # ------------------------------------------------------------------

    def get_required_checks(self) -> list[str]:
        """Return the list of checks that must pass (e.g. ``["pytest"]``)."""
        return list(self.required_checks)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _match_glob(path: str, pattern: str) -> bool:
    """Match *path* against a glob *pattern*.

    ``*`` matches any characters **except** ``/`` (single path component).
    ``**`` matches any characters **including** ``/`` (recursive).

    >>> _match_glob("src/main.py", "src/**")
    True
    >>> _match_glob("src/a/b/c.py", "src/**")
    True
    >>> _match_glob("src/main.py", "src/*.py")
    True
    >>> _match_glob("src/sub/main.py", "src/*.py")
    False
    """
    idx = pattern.find("**")
    if idx == -1:
        return _match_simple_glob(path, pattern)

    prefix = pattern[:idx]
    suffix = pattern[idx + 2:]

    if prefix and not path.startswith(prefix):
        return False

    remaining = path[len(prefix):]
    if suffix.startswith("/"):
        suffix = suffix[1:]

    if not suffix:
        return True

    # **/suffix — suffix must match at some depth in remaining
    parts = remaining.split("/")
    for i in range(len(parts)):
        candidate = "/".join(parts[i:])
        if _match_simple_glob(candidate, suffix):
            return True
    return False


def _match_simple_glob(path: str, pattern: str) -> bool:
    """Match *path* against *pattern* where ``*`` matches ``[^/]*``."""
    regex = re.escape(pattern)
    regex = regex.replace(r"\*", "[^/]*")
    regex = regex.replace(r"\?", "[^/]")
    regex = "^" + regex + "$"
    return bool(re.match(regex, path))


def _as_str_list(value: Any) -> list[str]:
    """Normalise a YAML value to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _normalise_tool_risk_levels(raw: dict[str, Any]) -> dict[str, str]:
    """Convert YAML tool section to ``{tool_name: risk_level}``."""
    result: dict[str, str] = {}
    for tool_name, config in raw.items():
        if isinstance(config, dict):
            result[tool_name] = str(config.get("risk_level", "low"))
        elif isinstance(config, str):
            result[tool_name] = config
        else:
            result[tool_name] = "low"
    return result


def load_policy(path: str | Path | None) -> Policy:
    """Load a policy from a YAML file path.

    Returns ``Policy.defaults()`` when *path* is ``None`` or the file does not exist.
    """
    if path is None:
        return Policy.defaults()
    file_path = Path(path)
    if not file_path.exists():
        return Policy.defaults()
    return Policy.from_yaml(file_path)
