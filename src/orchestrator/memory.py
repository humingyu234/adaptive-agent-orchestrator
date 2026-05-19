"""Memory layer — lightweight, inspectable project memory.

**CANONICAL memory lives in ``.aao/memory/``.**  This is the source of truth
for project constraints, architecture decisions, failure lessons, review
decisions, run summaries, user preferences, and worker lessons.

``outputs/memory/`` is a **LEGACY runtime artifact** (captured by the old
MemoryManager.capture path).  It is NOT canonical project memory.  Reports and
handoffs MUST NOT call it "memory" without disambiguation.

Memory is a hint with provenance, not evidence for the current run.
Every memory item declares where it came from and how confident we are.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# =============================================================================
# Core types
# =============================================================================

MemorySourceType = Literal["observed", "reported", "inferred"]

MemoryKind = Literal[
    "project_constraint",
    "architecture_decision",
    "failure_lesson",
    "review_decision",
    "run_summary",
    "user_preference",
    "worker_lesson",
]

# =============================================================================
# Secret detection — lightweight regex patterns
# =============================================================================

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:api[_-]?key|apikey|secret|token|password|passwd)\s*[:=]\s*['\"]?\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY-----"),
    re.compile(r"sk-[a-zA-Z0-9\-_]{20,}"),  # OpenAI-style keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PAT
    re.compile(r"gho_[a-zA-Z0-9]{36}"),  # GitHub OAuth
    re.compile(r"ghu_[a-zA-Z0-9]{36}"),  # GitHub user-to-server
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}"),  # JWT
]

# =============================================================================
# Reflection rules — deterministic gate for whether to store
# =============================================================================

def should_remember(
    *,
    kind: MemoryKind,
    source_type: MemorySourceType,
    content: str,
    is_transient: bool = False,
) -> bool:
    """Deterministic reflection gate.  Returns True if a memory item is worth storing."""
    if not source_type:
        return False
    if not kind:
        return False
    if not content.strip():
        return False
    if is_transient:
        return False
    if source_type == "reported" and kind in ("failure_lesson", "worker_lesson"):
        # Reported failures are less durable — only store if substance exists
        if len(content) < 40:
            return False
    return True


def redact_secrets(text: str) -> str:
    """Replace detected secrets with '[REDACTED]'."""
    result = text
    for pat in _SECRET_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


def contains_secrets(text: str) -> bool:
    """Return True if *text* likely contains secrets."""
    return any(pat.search(text) for pat in _SECRET_PATTERNS)


# =============================================================================
# MemoryItem — a single remembered thing
# =============================================================================


@dataclass
class MemoryItem:
    """One memory entry with full provenance."""

    id: str = ""
    kind: MemoryKind = "run_summary"
    source_type: MemorySourceType = "observed"
    title: str = ""
    content: str = ""
    created_at: str = ""
    updated_at: str = ""
    task_id: str = ""
    run_id: str = ""
    source_path: str = ""
    evidence_path: str = ""
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"mem-{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if self.source_type not in ("observed", "reported", "inferred"):
            raise ValueError(
                f"Invalid source_type: {self.source_type!r}. "
                "Must be 'observed', 'reported', or 'inferred'."
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "source_path": self.source_path,
            "evidence_path": self.evidence_path,
            "tags": self.tags,
            "confidence": self.confidence,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryItem:
        return cls(
            id=d.get("id", ""),
            kind=d.get("kind", "run_summary"),
            source_type=d.get("source_type", "observed"),
            title=d.get("title", ""),
            content=d.get("content", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            task_id=d.get("task_id", ""),
            run_id=d.get("run_id", ""),
            source_path=d.get("source_path", ""),
            evidence_path=d.get("evidence_path", ""),
            tags=d.get("tags", []),
            confidence=d.get("confidence", 0.5),
            expires_at=d.get("expires_at", ""),
        )


# =============================================================================
# MemoryContext — bounded snapshot for planning / control
# =============================================================================


@dataclass
class MemoryContext:
    """Small, bounded context passed to planning and control.

    Caps the number of items per category.  Do not dump the whole memory
    folder into a prompt or plan.
    """

    project_constraints: list[MemoryItem] = field(default_factory=list)
    relevant_decisions: list[MemoryItem] = field(default_factory=list)
    failure_lessons: list[MemoryItem] = field(default_factory=list)
    review_decisions: list[MemoryItem] = field(default_factory=list)
    user_preferences: list[MemoryItem] = field(default_factory=list)
    run_summaries: list[MemoryItem] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)

    def to_summary(self) -> dict:
        """Compact memory usage summary for reports."""
        by_source: dict[str, int] = {}
        all_items = (
            self.project_constraints
            + self.relevant_decisions
            + self.failure_lessons
            + self.review_decisions
            + self.user_preferences
            + self.run_summaries
        )
        for item in all_items:
            by_source[item.source_type] = by_source.get(item.source_type, 0) + 1
        return {
            "project_constraints": len(self.project_constraints),
            "relevant_decisions": len(self.relevant_decisions),
            "failure_lessons": len(self.failure_lessons),
            "review_decisions": len(self.review_decisions),
            "user_preferences": len(self.user_preferences),
            "run_summaries": len(self.run_summaries),
            "source_types": by_source,
            "total_items": len(all_items),
        }

    @property
    def is_empty(self) -> bool:
        return not any([
            self.project_constraints,
            self.relevant_decisions,
            self.failure_lessons,
            self.review_decisions,
            self.user_preferences,
            self.run_summaries,
        ])


# =============================================================================
# MemoryStore — local file-based persistent storage
# =============================================================================


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """Local inspectable file-based memory store.

    Canonical paths (per spec):
        .aao/memory/project.md
        .aao/memory/decisions/*.md
        .aao/memory/failures/*.json
        .aao/memory/runs/*.json
        .aao/memory/reviews/*.json
        .aao/memory/index.json

    Missing directories are created on write, not on init.
    Missing files do not crash reads.
    """

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self._base = self.project_root / ".aao" / "memory"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _decisions_dir(self) -> Path:
        return self._base / "decisions"

    def _failures_dir(self) -> Path:
        return self._base / "failures"

    def _runs_dir(self) -> Path:
        return self._base / "runs"

    def _reviews_dir(self) -> Path:
        return self._base / "reviews"

    def _index_path(self) -> Path:
        return self._base / "index.json"

    def _project_md_path(self) -> Path:
        return self._base / "project.md"

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, item: MemoryItem) -> MemoryItem:
        """Store a memory item and update the index.  Rejects invalid source types."""
        if item.source_type not in ("observed", "reported", "inferred"):
            raise ValueError(f"Invalid source_type: {item.source_type!r}")

        # Redact secrets in content and title
        item.content = redact_secrets(item.content)
        item.title = redact_secrets(item.title)

        # Persist to the appropriate subdirectory
        file_path = self._item_path(item)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Update index
        self._add_to_index(item, file_path)
        return item

    def _item_path(self, item: MemoryItem) -> Path:
        """Map MemoryKind to the correct storage directory."""
        kind_dirs: dict[MemoryKind, Path] = {
            "project_constraint": self._base,
            "architecture_decision": self._decisions_dir(),
            "failure_lesson": self._failures_dir(),
            "review_decision": self._reviews_dir(),
            "run_summary": self._runs_dir(),
            "user_preference": self._base,
            "worker_lesson": self._failures_dir(),
        }
        base = kind_dirs.get(item.kind, self._base)
        return base / f"{item.id}.json"

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, item_id: str) -> MemoryItem | None:
        """Load a single memory item by id.  Returns None if missing."""
        index = self._load_index()
        entry = next((e for e in index if e.get("id") == item_id), None)
        if entry is None:
            return None
        path = Path(entry["path"])
        if not path.exists():
            return None
        return MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8")))

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_items(
        self,
        *,
        kind: MemoryKind | None = None,
        source_type: MemorySourceType | None = None,
    ) -> list[MemoryItem]:
        """List all memory items, optionally filtered."""
        index = self._load_index()
        items: list[MemoryItem] = []
        for entry in index:
            if kind is not None and entry.get("kind") != kind:
                continue
            if source_type is not None and entry.get("source_type") != source_type:
                continue
            path = Path(entry["path"])
            if not path.exists():
                continue
            items.append(MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return items

    # ------------------------------------------------------------------
    # Retrieve — deterministic keyword/tag matching
    # ------------------------------------------------------------------

    def retrieve(
        self,
        *,
        query: str = "",
        tags: list[str] | None = None,
        kind: MemoryKind | None = None,
        source_type: MemorySourceType | None = None,
        top_k: int = 10,
    ) -> list[MemoryItem]:
        """Deterministic retrieval by keyword/tag/kind/source_type with top_k cap."""
        query_tokens = _tokenize(query) if query else set()
        tag_set = set(tags or [])
        index = self._load_index()
        if not index:
            return []

        scored: list[tuple[int, dict]] = []
        for entry in index:
            if kind is not None and entry.get("kind") != kind:
                continue
            if source_type is not None and entry.get("source_type") != source_type:
                continue

            entry_tags = set(entry.get("tags", []))
            entry_tokens = set(entry.get("tokens", []))

            score = 0
            if query_tokens:
                score += len(query_tokens & entry_tokens)
            if tag_set:
                score += len(tag_set & entry_tags) * 2  # tag match is stronger
            # Boost by recency
            created = entry.get("created_at", "")
            if created:
                score += 0.1  # slight recency boost for any timestamp

            if score > 0 or (not query and not tags):
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], x[1].get("created_at", "")), reverse=False)
        return self._resolve_entries(scored[:top_k])

    def retrieve_context(
        self,
        *,
        query: str = "",
        task_size: str = "medium",
        top_k_per_kind: int = 3,
    ) -> MemoryContext:
        """Build a bounded MemoryContext for planning/control.

        Caps items per kind.  Simple, deterministic, no LLM.
        """
        ctx = MemoryContext()
        ctx.project_constraints = self.retrieve(
            kind="project_constraint", top_k=top_k_per_kind,
        )
        ctx.relevant_decisions = self.retrieve(
            kind="architecture_decision", query=query, top_k=top_k_per_kind,
        )
        ctx.failure_lessons = self.retrieve(
            kind="failure_lesson", query=query, top_k=top_k_per_kind,
        )
        ctx.review_decisions = self.retrieve(
            kind="review_decision", top_k=top_k_per_kind,
        )
        ctx.user_preferences = self.retrieve(
            kind="user_preference", top_k=top_k_per_kind,
        )
        ctx.run_summaries = self.retrieve(
            kind="run_summary", query=query, top_k=max(1, top_k_per_kind // 2),
        )
        return ctx

    def record_failure_lesson(
        self,
        *,
        failure_category: str,
        reason: str,
        recovery_hint: str = "",
        what_prevents_repeat: str = "",
        source_type: MemorySourceType = "observed",
        evidence_path: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> MemoryItem:
        """Record a durable failure lesson.

        Does NOT record if the failure looks transient (short reason, no
        recovery hint, or source is reported without evidence path).
        """
        if source_type == "reported" and not evidence_path:
            source_type = "reported"
        item = MemoryItem(
            kind="failure_lesson",
            source_type=source_type,
            title=f"Failure: {failure_category}",
            content=(
                f"Category: {failure_category}\n"
                f"Reason: {reason}\n"
                f"Recovery hint: {recovery_hint or 'none'}\n"
                f"What prevents repeat: {what_prevents_repeat or 'unknown'}"
            ),
            task_id=task_id,
            run_id=run_id,
            evidence_path=evidence_path,
            tags=[failure_category, "failure"],
            confidence=0.7 if source_type == "observed" else 0.4,
        )
        return self.create(item)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _add_to_index(self, item: MemoryItem, file_path: Path) -> None:
        index = self._load_index()
        tokens = sorted(
            _tokenize(item.title) | _tokenize(item.content) | set(item.tags)
        )
        entry = {
            "id": item.id,
            "kind": item.kind,
            "source_type": item.source_type,
            "title": item.title,
            "path": str(file_path),
            "created_at": item.created_at,
            "tags": item.tags,
            "tokens": tokens,
            "task_id": item.task_id,
            "run_id": item.run_id,
        }
        index = [e for e in index if e.get("id") != item.id]
        index.append(entry)
        self._index_path().parent.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _load_index(self) -> list[dict]:
        ip = self._index_path()
        if not ip.exists():
            return []
        try:
            return json.loads(ip.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _resolve_entries(self, entries: list[tuple[int, dict]]) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for _, entry in entries:
            path = Path(entry["path"])
            if not path.exists():
                continue
            try:
                items.append(MemoryItem.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        return items


# =============================================================================
# Tokenizer — shared between MemoryManager (legacy) and MemoryStore
# =============================================================================


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9_一-鿿]+", text.lower()) if len(token) >= 2}
