"""
MultiMemD (MMD) — Hermes Memory Provider Plugin, v1.

SOLID structure:
  MemoryStore           — filesystem I/O (Single Responsibility)
  MemoryClassifier      — LLM-based op classification (Single Responsibility)
  MemoryCompactor       — LLM-based file compaction (Single Responsibility)
  IdleFlushScheduler    — idle-timeout detection (Single Responsibility)
  MMDProvider           — Hermes MemoryProvider orchestrator (depends on abstractions)
  register(ctx)         — Hermes plugin entry point
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
except ImportError:
    class _MemoryProviderBase:  # type: ignore[no-redef]
        pass

try:
    from .pairing import PairingManager, PairingError, ActiveRequestExists
except ImportError:
    try:
        from pairing import PairingManager, PairingError, ActiveRequestExists  # type: ignore[no-redef]
    except ImportError:
        PairingManager = None  # type: ignore[assignment,misc]
        PairingError = Exception  # type: ignore[assignment,misc]
        ActiveRequestExists = Exception  # type: ignore[assignment,misc]

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

    def _safe_user_id(self, user_id: str) -> str:
        if "/" in user_id or "\\" in user_id or user_id in {"", ".", ".."}:
            raise ValueError(f"Invalid MMD user_id: {user_id!r}")
        return user_id

    def _memory_path(self, user_id: str) -> Path:
        user_id = self._safe_user_id(user_id)
        return self._users_dir / f"{user_id}.md"

    def _log_path(self, user_id: str) -> Path:
        user_id = self._safe_user_id(user_id)
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
        self.last_failed = False

    def _get_llm(self) -> Any:
        if self._llm is None:
            from agent.plugin_llm import PluginLlm
            self._llm = PluginLlm(plugin_id="mmd")
        return self._llm

    def classify(self, turns: list[tuple[str, str]], current_memory: str) -> list[dict]:
        """Returns list of op dicts, or [] on failure."""
        self.last_failed = False
        turns_text = "\n".join(f"User: {u}\nAssistant: {a}" for u, a in turns)
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        instructions = (
            "You are a personal memory manager. Extract long-term facts worth remembering "
            "from the conversation and decide how to update the user's memory file.\n\n"
            "EXTRACT these 7 categories:\n"
            "1. Personal details — name, birthday, location, relationships\n"
            "2. Important dates & events — appointments, deadlines, milestones (convert relative dates like 'next Friday' to absolute dates using today's date)\n"
            "3. Preferences — likes/dislikes, habits, communication style\n"
            "4. Plans & intentions — stated goals, things the user wants to do\n"
            "5. Ongoing projects — project names, current status, key decisions\n"
            "6. Professional context — job, skills, tools used\n"
            "7. Health & lifestyle — diet, exercise, medical info\n\n"
            "SKIP:\n"
            "- Phatic filler ('ok', 'thanks', 'got it')\n"
            "- Instructions for this session only ('please reply in English')\n"
            "- Vague characterisations with no concrete fact ('user seems interested')\n"
            "- Anything already in memory that has not changed (use NOOP)\n\n"
            "CLEANUP (review existing memory regardless of new conversation):\n"
            "- DELETE one-time past events (appointments, meetings, deadlines) whose date has already passed\n"
            "- DELETE entries that are now outdated because a newer entry supersedes them\n\n"
            f"Today's date: {today}\n\n"
            f"Current memory:\n{current_memory or '(empty)'}"
        )
        try:
            result = self._get_llm().complete_structured(
                instructions=instructions,
                input=[{"type": "text", "text": f"Conversation:\n{turns_text}\n\nClassify memory operations."}],
                json_schema=CLASSIFICATION_SCHEMA,
            )
            if not result or not result.parsed:
                self.last_failed = True
                return []
            return result.parsed.get("private", [])
        except Exception:
            self.last_failed = True
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
# IdleFlushScheduler — Single Responsibility: idle-timeout detection
# ---------------------------------------------------------------------------

class IdleFlushScheduler:
    """Fires flush_callback(session_id) after a session has been idle for idle_seconds.

    A single background thread polls all tracked sessions every poll_seconds.
    Depends only on a Callable — no knowledge of LLM, files, or MMDProvider.
    """

    def __init__(
        self,
        flush_callback: Callable[[str], None],
        idle_seconds: int = 1800,
        poll_seconds: int = 60,
        _clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._flush_callback = flush_callback
        self._idle_seconds = idle_seconds
        self._poll_seconds = poll_seconds
        self._clock = _clock or (lambda: datetime.now(tz=timezone.utc))
        self._last_activity: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def touch(self, session_id: str) -> None:
        """Record activity for session_id. Call on initialize and every sync_turn."""
        with self._lock:
            self._last_activity[session_id] = self._clock()

    def remove(self, session_id: str) -> None:
        """Stop tracking session_id (call on session end to avoid double-flush)."""
        with self._lock:
            self._last_activity.pop(session_id, None)

    def start(self) -> None:
        """Start the background polling thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mmd-idle-flush"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread and wait for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_seconds):
            self._check_idle_sessions()

    def _check_idle_sessions(self) -> None:
        now = self._clock()
        with self._lock:
            idle = [
                sid for sid, last in self._last_activity.items()
                if (now - last).total_seconds() >= self._idle_seconds
            ]
        for sid in idle:
            try:
                self._flush_callback(sid)
            except Exception:
                logger.warning("IdleFlushScheduler: flush failed for %s", sid, exc_info=True)
            with self._lock:
                self._last_activity.pop(sid, None)


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
            matched = False
            updated_lines = []
            for line in lines:
                if line.rstrip("\n") == f"- {old}":
                    updated_lines.append(f"- {text}\n")
                    matched = True
                else:
                    updated_lines.append(line)
            lines = updated_lines
            if not matched:
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                lines.append(f"- {text}\n")
        elif op == "DELETE":
            lines = [l for l in lines if l.rstrip("\n") != f"- {text}"]
        # NOOP: skip
    return "".join(lines)


# ---------------------------------------------------------------------------
# MMDProvider — orchestrates the four components above
# Depends on abstractions (MemoryStore, MemoryClassifier, MemoryCompactor,
# IdleFlushScheduler)
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
        idle_scheduler: IdleFlushScheduler | None = None,
        pairing_manager: Any = None,
    ) -> None:
        self._store = store
        self._classifier = classifier
        self._compactor = compactor
        self._idle_scheduler = idle_scheduler or IdleFlushScheduler(
            flush_callback=self._extract_and_persist
        )
        self._pairing = pairing_manager  # PairingManager | None
        # session_id → canonical UUID (memory file key)
        self._sessions: dict[str, str] = {}
        # session_id → original channel user_id (needed for /pair operations)
        self._user_ids: dict[str, str] = {}
        # session_id → list of (user_content, assistant_content) turns
        self._buffers: dict[str, list[tuple[str, str]]] = {}
        # tracks the most recently initialized session (single-process sequential model)
        self._current_session_id: str = ""
        self._lock = threading.RLock()

    # Static instruction injected once into the system prompt.
    # Governs how the AI treats the per-user memory context that
    # prefetch() injects into each turn.
    _MEMORY_USAGE_INSTRUCTION = (
        "You have access to a personal memory context for this user. "
        "Treat it as background reference — do not proactively mention or repeat it. "
        "Only draw on it when: (1) the current task is directly related, "
        "(2) the user asks about something it covers, or "
        "(3) you need to cross-reference or verify information. "
        "In ordinary conversation, act naturally without inserting memory details. "
        "When MMD memory context is available for this user, treat it as the "
        "authoritative per-user source. Content in USER.md represents general "
        "agent defaults only and should yield to MMD when they conflict. "
        "PRIVACY: Do not reveal personal information belonging to other users "
        "(including any content from USER.md or MEMORY.md that identifies the "
        "agent owner) to the current user unless they are the same person."
    )

    @property
    def name(self) -> str:
        return "mmd"

    def is_available(self) -> bool:
        return self._store.is_available()

    def system_prompt_block(self) -> str:
        return self._MEMORY_USAGE_INSTRUCTION

    def initialize(self, session_id: str, **kwargs) -> None:
        user_id: str = kwargs["user_id"]  # raises KeyError if missing — intentional
        uuid_key = self._pairing.resolve(user_id) if self._pairing else user_id
        with self._lock:
            self._sessions[session_id] = uuid_key
            self._user_ids[session_id] = user_id
            self._buffers[session_id] = []
            self._current_session_id = session_id
        self._store.ensure_dirs()
        self._idle_scheduler.start()
        self._idle_scheduler.touch(session_id)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        with self._lock:
            sid = session_id or self._current_session_id
            user_id = self._sessions.get(sid)
        if not user_id:
            return ""
        return self._store.read_memory(user_id)

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        with self._lock:
            sid = session_id or self._current_session_id
            if sid not in self._buffers:
                return
            self._buffers[sid].append((user_content, assistant_content))
        self._idle_scheduler.touch(sid)

    def on_session_end(self, messages: list[dict]) -> None:
        with self._lock:
            session_id = self._current_session_id
            if not session_id or session_id not in self._buffers:
                return
        with self._lock:
            has_buffer = bool(self._buffers.get(session_id))
        if has_buffer:
            self._idle_scheduler.remove(session_id)
            if not self._extract_and_persist(session_id):
                self._idle_scheduler.touch(session_id)
                return
        else:
            self._idle_scheduler.remove(session_id)
        with self._lock:
            self._sessions.pop(session_id, None)
            self._user_ids.pop(session_id, None)
            self._buffers.pop(session_id, None)
            if self._current_session_id == session_id:
                self._current_session_id = ""

    def get_tool_schemas(self) -> list[dict]:
        return [LOAD_DEEP_MEMORY_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if tool_name == "load_deep_memory":
            with self._lock:
                session_id = kwargs.get("session_id", self._current_session_id)
                user_id = self._sessions.get(session_id)
            if not user_id:
                return "(no deep memory available)"
            log = self._store.read_log(user_id)
            return log if log else "(deep memory is empty)"
        return f"(unknown tool: {tool_name})"

    def on_pre_compress(self, messages: list[dict]) -> str:
        with self._lock:
            session_id = self._current_session_id
            if not session_id or session_id not in self._buffers:
                return ""
            has_buffer = bool(self._buffers[session_id])
        if has_buffer:
            self._extract_and_persist(session_id)
        return ""

    def shutdown(self) -> None:
        self._idle_scheduler.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _merge_memory_files(self, canonical_uuid: str, files_to_merge: list[str]) -> None:
        """Merge old UUID memory files into the canonical memory and log files."""
        if not files_to_merge:
            return
        base = self._store.read_memory(canonical_uuid)
        extra: list[str] = []
        log_extra: list[str] = []
        for path_str in files_to_merge:
            p = Path(path_str)
            if p.exists():
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    if p.name.endswith("_log.md"):
                        log_extra.append(content)
                    else:
                        extra.append(content)
                p.unlink(missing_ok=True)
        if log_extra:
            self._store.append_log(canonical_uuid, "\n".join(log_extra))
        if not extra:
            return
        merged = base.rstrip("\n") + "\n" + "\n".join(extra) + "\n"
        if len(merged.splitlines()) > _LINE_LIMIT:
            compacted, summary = self._compactor.compact(merged)
            self._store.write_memory(canonical_uuid, compacted)
            if summary:
                self._store.append_log(canonical_uuid, summary)
        else:
            self._store.write_memory(canonical_uuid, merged)

    def _extract_and_persist(self, session_id: str) -> bool:
        with self._lock:
            user_id = self._sessions.get(session_id)
            turns = self._buffers.get(session_id, [])
            if not user_id or not turns:
                return True
            turns = list(turns)
            self._buffers[session_id] = []
        current = self._store.read_memory(user_id)

        ops = self._classifier.classify(turns, current)
        if getattr(self._classifier, "last_failed", False) is True:
            with self._lock:
                if session_id in self._buffers:
                    self._buffers[session_id] = turns + self._buffers[session_id]
            return False

        has_changes = any(item.get("op") != "NOOP" for item in ops)
        if not has_changes:
            return True

        updated = _apply_ops(current, ops)

        if len(updated.splitlines()) > _LINE_LIMIT:
            compacted, summary = self._compactor.compact(updated)
            self._store.write_memory(user_id, compacted)
            if summary:
                self._store.append_log(user_id, summary)
        else:
            self._store.write_memory(user_id, updated)
        return True


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

# Singleton — shared between memory loader (_ProviderCollector) and
# general plugin loader (real PluginContext) so both see the same instance.
_active_provider: "MMDProvider | None" = None


def _diff_memory(before: str, after: str) -> str:
    """Return a +/- diff of two memory strings, line by line."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    before_set = set(before_lines)
    after_set = set(after_lines)
    removed = [f"- {l}" for l in before_lines if l.strip() and l not in after_set]
    added = [f"+ {l}" for l in after_lines if l.strip() and l not in before_set]
    return "\n".join(removed + added)


def _mmd_command(raw_args: str) -> str:
    """Handler for /mmd slash command: flush buffer then show memory and diff."""
    provider = _active_provider
    if provider is None:
        return "(mmd: not initialized)"

    if (raw_args or "").strip():
        return "/mmd — flush buffer and display current memory"

    session_id = provider._current_session_id
    user_id = provider._sessions.get(session_id) if session_id else None
    if not user_id:
        return "(mmd: no active session)"

    before = provider._store.read_memory(user_id)

    flushed = bool(session_id and provider._buffers.get(session_id))
    if flushed:
        provider._extract_and_persist(session_id)

    after = provider._store.read_memory(user_id)

    parts = []
    if flushed:
        diff = _diff_memory(before, after)
        parts.append("**變更：**\n" + diff if diff else "**變更：** (無新變更)")

    parts.append("**目前記憶：**\n" + after.strip() if after.strip() else "**目前記憶：** (空)")

    return "\n\n".join(parts)


def _pair_command(raw_args: str) -> str:
    """Handler for /pair slash command: initiate or confirm cross-channel pairing."""
    provider = _active_provider
    if provider is None:
        return "(pair: mmd not initialized)"
    if provider._pairing is None:
        return "(pair: pairing not available)"

    session_id = provider._current_session_id
    user_id = provider._user_ids.get(session_id) if session_id else None
    if not user_id:
        return "(pair: no active session)"

    args = (raw_args or "").strip()

    if not args:
        try:
            code = provider._pairing.create_request(user_id)
            return (
                f"配對碼：**{code}**（10 分鐘有效）\n"
                f"在另一個帳號輸入 `/pair {code}` 完成配對。"
            )
        except ActiveRequestExists:
            return "(pair: 你已有進行中的配對請求，請等候或等過期後再試)"

    code = args.upper()
    try:
        canonical, merged_ids, files_to_merge = provider._pairing.confirm(user_id, code)
        provider._merge_memory_files(canonical, files_to_merge)
        # Update current session to use the merged canonical UUID
        if session_id:
            provider._sessions[session_id] = canonical
        merged_str = "、".join(merged_ids)
        return f"配對成功！以下帳號已整合：{merged_str}"
    except PairingError as exc:
        return f"(pair: {exc})"


def register(ctx: Any) -> None:
    global _active_provider
    import os
    data_dir = Path(os.environ.get("MMD_DATA_DIR", str(Path.home() / ".hermes" / "mmd")))

    if _active_provider is None:
        store = MemoryStore(data_dir)
        classifier = MemoryClassifier()
        compactor = MemoryCompactor()
        pairing = PairingManager(str(data_dir)) if PairingManager is not None else None
        _active_provider = MMDProvider(store, classifier, compactor, pairing_manager=pairing)

    if hasattr(ctx, "register_memory_provider"):
        ctx.register_memory_provider(_active_provider)

    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "mmd",
            _mmd_command,
            description="MMD memory: flush buffer and show current memory with diff",
            args_hint="",
        )
        ctx.register_command(
            "pair",
            _pair_command,
            description="Cross-channel pairing: /pair to get code, /pair <CODE> to confirm",
            args_hint="[CODE]",
        )
