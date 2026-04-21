"""ProjectContext - ????????"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class FileInfo:
    path: str
    name: str
    extension: str
    size_bytes: int
    is_directory: bool
    relative_path: str
    depth: int
    modified_at: str = ""

    def __post_init__(self) -> None:
        if not self.modified_at:
            self.modified_at = datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectStructure:
    root_path: str
    total_files: int
    total_directories: int
    total_size_bytes: int
    file_types: dict[str, int] = field(default_factory=dict)
    top_level_items: list[FileInfo] = field(default_factory=list)
    scanned_at: str = ""

    def __post_init__(self) -> None:
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()


@dataclass
class FileSummary:
    path: str
    content_preview: str
    line_count: int
    char_count: int
    language: str
    has_syntax_errors: bool = False
    summary: str = ""


DEFAULT_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache",
    ".mypy_cache", "dist", "build", ".egg-info", "outputs",
}
DEFAULT_EXCLUDE_FILES = {".gitignore", ".env", "*.pyc", "*.pyo", "__init__.py"}
KEY_FILE_PATTERNS = ["*.py", "*.yaml", "*.yml", "*.json", "*.md", "*.txt"]


class ProjectContext:
    def __init__(
        self,
        project_root: Path,
        exclude_dirs: set[str] | None = None,
        exclude_files: set[str] | None = None,
        max_preview_lines: int = 50,
    ) -> None:
        self.project_root = Path(project_root)
        self.exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS
        self.exclude_files = exclude_files or DEFAULT_EXCLUDE_FILES
        self.max_preview_lines = max_preview_lines
        self._structure: ProjectStructure | None = None
        self._file_cache: dict[str, FileSummary] = {}

    def scan(self, force: bool = False) -> ProjectStructure:
        if self._structure is not None and not force:
            return self._structure

        file_types: dict[str, int] = {}
        top_level_items: list[FileInfo] = []
        total_files = 0
        total_directories = 0
        total_size = 0

        for item in self.project_root.iterdir():
            if item.name in self.exclude_dirs:
                continue
            if item.is_file() and self._should_exclude_file(item.name):
                continue

            info = self._create_file_info(item, depth=0)
            top_level_items.append(info)

            if item.is_dir():
                total_directories += 1
                sub_stats = self._scan_directory(item, depth=1)
                total_files += sub_stats["files"]
                total_directories += sub_stats["directories"]
                total_size += sub_stats["size"]
                for ext, count in sub_stats["types"].items():
                    file_types[ext] = file_types.get(ext, 0) + count
            else:
                total_files += 1
                total_size += info.size_bytes
                ext = info.extension.lower()
                if ext:
                    file_types[ext] = file_types.get(ext, 0) + 1

        self._structure = ProjectStructure(
            root_path=str(self.project_root),
            total_files=total_files,
            total_directories=total_directories,
            total_size_bytes=total_size,
            file_types=file_types,
            top_level_items=top_level_items,
        )
        return self._structure

    def _scan_directory(self, directory: Path, depth: int) -> dict[str, Any]:
        stats: dict[str, Any] = {"files": 0, "directories": 0, "size": 0, "types": {}}
        try:
            for item in directory.iterdir():
                if item.name in self.exclude_dirs:
                    continue
                if item.is_file() and self._should_exclude_file(item.name):
                    continue

                info = self._create_file_info(item, depth)
                if item.is_dir():
                    stats["directories"] += 1
                    sub_stats = self._scan_directory(item, depth + 1)
                    stats["files"] += sub_stats["files"]
                    stats["directories"] += sub_stats["directories"]
                    stats["size"] += sub_stats["size"]
                    for ext, count in sub_stats["types"].items():
                        stats["types"][ext] = stats["types"].get(ext, 0) + count
                else:
                    stats["files"] += 1
                    stats["size"] += info.size_bytes
                    ext = info.extension.lower()
                    if ext:
                        stats["types"][ext] = stats["types"].get(ext, 0) + 1
        except OSError:
            pass
        return stats

    def _should_exclude_file(self, filename: str) -> bool:
        return any(fnmatch.fnmatch(filename, pattern) for pattern in self.exclude_files)

    def _create_file_info(self, path: Path, depth: int) -> FileInfo:
        try:
            stat = path.stat()
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        except OSError:
            size = 0
            modified = ""

        return FileInfo(
            path=str(path),
            name=path.name,
            extension=path.suffix.lstrip("."),
            is_directory=path.is_dir(),
            relative_path=str(path.relative_to(self.project_root)),
            depth=depth,
            size_bytes=size,
            modified_at=modified,
        )

    def get_file_summary(self, relative_path: str) -> FileSummary | None:
        if relative_path in self._file_cache:
            return self._file_cache[relative_path]

        file_path = self.project_root / relative_path
        if not file_path.exists() or not file_path.is_file():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        lines = content.split("\n")
        preview = "\n".join(lines[:self.max_preview_lines])
        language = self._detect_language(file_path.suffix)

        has_syntax_errors = False
        if language == "python":
            try:
                compile(content, str(file_path), "exec")
            except SyntaxError:
                has_syntax_errors = True

        summary = FileSummary(
            path=relative_path,
            content_preview=preview,
            line_count=len(lines),
            char_count=len(content),
            language=language,
            has_syntax_errors=has_syntax_errors,
        )
        self._file_cache[relative_path] = summary
        return summary

    def _detect_language(self, extension: str) -> str:
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".md": "markdown",
            ".txt": "text", ".html": "html", ".css": "css", ".sh": "shell", ".bat": "batch",
        }
        return ext_map.get(extension.lower(), "unknown")

    def find_files(self, pattern: str = "*", extension: str | None = None, max_depth: int | None = None) -> list[FileInfo]:
        if self._structure is None:
            self.scan()

        results = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [directory for directory in dirs if directory not in self.exclude_dirs]
            rel_path = Path(root).relative_to(self.project_root)
            depth = len(rel_path.parts)
            if max_depth is not None and depth > max_depth:
                continue

            for filename in files:
                if self._should_exclude_file(filename):
                    continue
                file_path = Path(root) / filename
                if pattern != "*" and not file_path.match(pattern):
                    continue
                if extension and file_path.suffix.lstrip(".").lower() != extension.lower():
                    continue
                results.append(self._create_file_info(file_path, depth))

        return results

    def get_context_for_agent(self, reads: list[str]) -> dict[str, Any]:
        context: dict[str, Any] = {}

        if "project_structure" in reads:
            if self._structure is None:
                self.scan()
            context["project_structure"] = {
                "total_files": self._structure.total_files,
                "total_directories": self._structure.total_directories,
                "file_types": self._structure.file_types,
                "top_level_items": [
                    {"name": item.name, "type": "dir" if item.is_directory else "file"}
                    for item in self._structure.top_level_items
                ],
            }

        if "key_files" in reads:
            key_files = []
            seen_paths: set[str] = set()
            for pattern in KEY_FILE_PATTERNS:
                files = self.find_files(pattern=pattern, max_depth=3)
                for file_info in files[:5]:
                    if file_info.relative_path in seen_paths:
                        continue
                    summary = self.get_file_summary(file_info.relative_path)
                    if summary:
                        seen_paths.add(file_info.relative_path)
                        key_files.append({
                            "path": file_info.relative_path,
                            "language": summary.language,
                            "lines": summary.line_count,
                        })
            context["key_files"] = key_files

        return context

    def get_summary_text(self) -> str:
        if self._structure is None:
            self.scan()

        lines = [
            f"Root: {self._structure.root_path}",
            f"Total files: {self._structure.total_files}",
            f"Total directories: {self._structure.total_directories}",
            f"Total size: {self._structure.total_size_bytes / 1024:.1f} KB",
            "",
            "Top file types:",
        ]

        for ext, count in sorted(self._structure.file_types.items(), key=lambda item: -item[1])[:10]:
            lines.append(f"  {ext or '[no extension]'}: {count}")

        lines.append("")
        lines.append("Top-level items:")
        for item in self._structure.top_level_items[:10]:
            type_str = "[DIR]" if item.is_directory else "[FILE]"
            lines.append(f"  {type_str} {item.name}")

        return "\n".join(lines)
