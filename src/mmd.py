"""
MultiMemD (MMD) — Hermes Memory Provider Plugin, v1.

SOLID structure:
  MemoryStore       — filesystem I/O (Single Responsibility)
  MemoryClassifier  — LLM-based op classification (Single Responsibility)
  MemoryCompactor   — LLM-based file compaction (Single Responsibility)
  MMDProvider       — Hermes MemoryProvider orchestrator (depends on abstractions)
  register(ctx)     — Hermes plugin entry point
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
except ImportError:
    class _MemoryProviderBase:  # type: ignore[no-redef]
        pass

_LINE_LIMIT = 200

# ---------------------------------------------------------------------------
# JSON schemas for ctx.llm.complete_structured()
# ---------------------------------------------------------------------------

CLASSIFICATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "private": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE", "NOOP"]},
                    "content": {"type": "string"},
                    "old": {"type": "string"},
                },
                "required": ["op", "content"],
            },
        }
    },
    "required": ["private"],
}

COMPACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "compacted": {"type": "string"},
        "removed_summary": {"type": "string"},
    },
    "required": ["compacted", "removed_summary"],
}

LOAD_DEEP_MEMORY_SCHEMA: dict = {
    "name": "load_deep_memory",
    "description": (
        "Load archived deep memory for the current user. "
        "Call this when the user asks about something that may have been mentioned "
        "long ago, or when current memory seems incomplete."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

# ---------------------------------------------------------------------------
# MemoryStore — Single Responsibility: filesystem operations
# ---------------------------------------------------------------------------

class MemoryStore:
    """Handles all file I/O for user memory files. No LLM interaction."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._users_dir = data_dir / "users"

    def is_available(self) -> bool:
        return bool(self._data_dir)

    def ensure_dirs(self) -> None:
        self._users_dir.mkdir(parents=True, exist_ok=True)

    def _memory_path(self, user_id: str) -> Path:
        return self._users_dir / f"{user_id}.md"

    def _log_path(self, user_id: str) -> Path:
        return self._users_dir / f"{user_id}_log.md"

    def read_memory(self, user_id: str) -> str:
        path = self._memory_path(user_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_memory(self, user_id: str, content: str) -> None:
        path = self._memory_path(user_id)
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(path)

    def read_log(self, user_id: str) -> str:
        path = self._log_path(user_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def append_log(self, user_id: str, summary: str) -> None:
        path = self._log_path(user_id)
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        block = f"\n## [{ts}]\n{summary}\n"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text(existing + block, encoding="utf-8")
        tmp.rename(path)

    def line_count(self, user_id: str) -> int:
        path = self._memory_path(user_id)
        return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


# ---------------------------------------------------------------------------
# MemoryClassifier — Single Responsibility: LLM-based op classification
# ---------------------------------------------------------------------------

class MemoryClassifier:
    """Classifies conversation turns into ADD/UPDATE/DELETE/NOOP memory ops."""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm  # injected in tests; None → lazy PluginLlm in production

    def _get_llm(self) -> Any:
        if self._llm is None:
            from agent.plugin_llm import PluginLlm
            self._llm = PluginLlm(plugin_id="mmd")
        return self._llm

    def classify(self, turns: list[tuple[str, str]], current_memory: str) -> list[dict]:
        """Returns list of op dicts, or [] on failure."""
        turns_text = "\n".join(f"User: {u}\nAssistant: {a}" for u, a in turns)
        instructions = (
            "You are a memory manager. Given a conversation and the user's current memory, "
            "classify what should be added, updated, deleted, or left unchanged (NOOP).\n"
            f"Current memory:\n{current_memory or '(empty)'}"
        )
        try:
            result = self._get_llm().complete_structured(
                instructions=instructions,
                input=[{"type": "text", "text": f"Conversation:\n{turns_text}\n\nClassify memory operations."}],
                json_schema=CLASSIFICATION_SCHEMA,
            )
            if not result or not result.parsed:
                return []
            return result.parsed.get("private", [])
        except Exception:
            logger.warning("MemoryClassifier: LLM call failed", exc_info=True)
            return []


# ---------------------------------------------------------------------------
# MemoryCompactor — Single Responsibility: LLM-based file size reduction
# ---------------------------------------------------------------------------

class MemoryCompactor:
    """Compacts a memory file to ≤200 lines while archiving removed content."""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm  # injected in tests; None → lazy PluginLlm in production

    def _get_llm(self) -> Any:
        if self._llm is None:
            from agent.plugin_llm import PluginLlm
            self._llm = PluginLlm(plugin_id="mmd")
        return self._llm

    def compact(self, content: str) -> tuple[str, str]:
        """Returns (compacted_content, removed_summary). Falls back to original on failure."""
        instructions = (
            "You are a memory compactor. Rewrite the memory file to under 200 lines "
            "by removing the least important or least recently referenced entries. "
            "Return the compacted file and a brief summary of what was removed."
        )
        try:
            result = self._get_llm().complete_structured(
                instructions=instructions,
                input=[{"type": "text", "text": content}],
                json_schema=COMPACTION_SCHEMA,
            )
            if not result or not result.parsed:
                return content, ""
            return result.parsed.get("compacted", content), result.parsed.get("removed_summary", "")
        except Exception:
            logger.warning("MemoryCompactor: LLM call failed", exc_info=True)
            return content, ""


# ---------------------------------------------------------------------------
# Pure helper — no class needed, no side effects
# ---------------------------------------------------------------------------

def _apply_ops(content: str, ops: list[dict]) -> str:
    """Apply ADD/UPDATE/DELETE/NOOP ops to memory file content string."""
    lines = content.splitlines(keepends=True)
    for item in ops:
        op = item.get("op", "NOOP")
        text = item.get("content", "")
        if op == "ADD":
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"- {text}\n")
        elif op == "UPDATE":
            old = item.get("old", "")
            lines = [
                f"- {text}\n" if line.rstrip("\n") == f"- {old}" else line
                for line in lines
            ]
        elif op == "DELETE":
            lines = [l for l in lines if l.rstrip("\n") != f"- {text}"]
        # NOOP: skip
    return "".join(lines)


# ---------------------------------------------------------------------------
# MMDProvider — orchestrates the three components above
# Depends on abstractions (MemoryStore, MemoryClassifier, MemoryCompactor)
# ---------------------------------------------------------------------------

class MMDProvider(_MemoryProviderBase):
    """
    Hermes MemoryProvider plugin for per-user Markdown memory.

    Implements the MemoryProvider abstract base class from
    NousResearch/hermes-agent: agent/memory_provider.py.
    All methods are synchronous.
    """

    def __init__(
        self,
        store: MemoryStore,
        classifier: MemoryClassifier,
        compactor: MemoryCompactor,
    ) -> None:
        self._store = store
        self._classifier = classifier
        self._compactor = compactor
        # session_id → user_id; cleared on session end
        self._sessions: dict[str, str] = {}
        # session_id → list of (user_content, assistant_content) turns
        self._buffers: dict[str, list[tuple[str, str]]] = {}
        # tracks the most recently initialized session (single-process sequential model)
        self._current_session_id: str = ""

    @property
    def name(self) -> str:
        return "mmd"

    def is_available(self) -> bool:
        return self._store.is_available()

    def initialize(self, session_id: str, **kwargs) -> None:
        user_id: str = kwargs["user_id"]  # raises KeyError if missing — intentional
        self._sessions[session_id] = user_id
        self._buffers[session_id] = []
        self._current_session_id = session_id
        self._store.ensure_dirs()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        user_id = self._sessions.get(session_id)
        if not user_id:
            return ""
        return self._store.read_memory(user_id)

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        if session_id in self._buffers:
            self._buffers[session_id].append((user_content, assistant_content))

    def on_session_end(self, messages: list[dict]) -> None:
        session_id = self._current_session_id
        if not session_id or session_id not in self._buffers:
            return
        if self._buffers[session_id]:
            self._extract_and_persist(session_id)
        self._sessions.pop(session_id, None)
        self._buffers.pop(session_id, None)
        self._current_session_id = ""

    def get_tool_schemas(self) -> list[dict]:
        return [LOAD_DEEP_MEMORY_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if tool_name == "load_deep_memory":
            session_id = kwargs.get("session_id", self._current_session_id)
            user_id = self._sessions.get(session_id)
            if not user_id:
                return "(no deep memory available)"
            log = self._store.read_log(user_id)
            return log if log else "(deep memory is empty)"
        return f"(unknown tool: {tool_name})"

    def shutdown(self) -> None:
        pass  # v1: all ops synchronous, nothing to drain

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_and_persist(self, session_id: str) -> None:
        user_id = self._sessions[session_id]
        turns = self._buffers[session_id]
        current = self._store.read_memory(user_id)

        ops = self._classifier.classify(turns, current)
        self._buffers[session_id] = []

        has_changes = any(item.get("op") != "NOOP" for item in ops)
        if not has_changes:
            return

        updated = _apply_ops(current, ops)

        if len(updated.splitlines()) > _LINE_LIMIT:
            compacted, summary = self._compactor.compact(updated)
            self._store.write_memory(user_id, compacted)
            if summary:
                self._store.append_log(user_id, summary)
        else:
            self._store.write_memory(user_id, updated)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

# Singleton — shared between memory loader (_ProviderCollector) and
# general plugin loader (real PluginContext) so both see the same instance.
_active_provider: "MMDProvider | None" = None


def _mmd_command(raw_args: str) -> str:
    """Handler for /mmd slash command."""
    provider = _active_provider
    if provider is None:
        return "(mmd: not initialized)"

    sub = (raw_args or "").strip().lower()
    session_id = provider._current_session_id
    user_id = provider._sessions.get(session_id) if session_id else None

    if sub in ("show", ""):
        if not user_id:
            return "(mmd: no active session)"
        content = provider._store.read_memory(user_id)
        return content if content.strip() else "(mmd: memory is empty)"

    if sub == "flush":
        if not session_id or not provider._buffers.get(session_id):
            return "(mmd: nothing to flush)"
        provider._extract_and_persist(session_id)
        return "(mmd: flushed)"

    return "/mmd [show|flush]\n  show  — display current memory\n  flush — extract and save buffer now"


def register(ctx: Any) -> None:
    global _active_provider
    import os
    data_dir = Path(os.environ.get("MMD_DATA_DIR", str(Path.home() / ".hermes" / "mmd")))

    if _active_provider is None:
        store = MemoryStore(data_dir)
        classifier = MemoryClassifier()
        compactor = MemoryCompactor()
        _active_provider = MMDProvider(store, classifier, compactor)

    if hasattr(ctx, "register_memory_provider"):
        ctx.register_memory_provider(_active_provider)

    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "mmd",
            _mmd_command,
            description="MMD memory: show current memory or flush buffer now",
            args_hint="[show|flush]",
        )
