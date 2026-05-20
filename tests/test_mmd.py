"""
TDD tests for src/mmd.py — MMD v1 per-user memory plugin.

Structure mirrors the SOLID class decomposition:
  TestMemoryStore       — file I/O, no mocks
  TestMemoryClassifier  — LLM classification, ctx mocked
  TestMemoryCompactor   — LLM compaction, ctx mocked
  TestMMDProvider       — orchestration, all dependencies mocked
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class TestMemoryStore:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        from src.mmd import MemoryStore
        self.store = MemoryStore(Path(self.tmp))

    def test_ensure_dirs_creates_users_directory(self):
        self.store.ensure_dirs()
        assert (Path(self.tmp) / "users").exists()

    def test_is_available_returns_true(self):
        assert self.store.is_available() is True

    def test_read_memory_returns_empty_for_new_user(self):
        self.store.ensure_dirs()
        assert self.store.read_memory("telegram_123") == ""

    def test_read_memory_returns_file_contents(self):
        self.store.ensure_dirs()
        (Path(self.tmp) / "users" / "telegram_123.md").write_text("# Memory\n- fact", encoding="utf-8")
        assert self.store.read_memory("telegram_123") == "# Memory\n- fact"

    def test_write_memory_creates_file(self):
        self.store.ensure_dirs()
        self.store.write_memory("telegram_123", "# Memory\n- fact")
        assert (Path(self.tmp) / "users" / "telegram_123.md").read_text(encoding="utf-8") == "# Memory\n- fact"

    def test_write_memory_leaves_no_tmp_file(self):
        self.store.ensure_dirs()
        self.store.write_memory("telegram_123", "content")
        assert not (Path(self.tmp) / "users" / "telegram_123.md.tmp").exists()

    def test_read_log_returns_empty_for_new_user(self):
        self.store.ensure_dirs()
        assert self.store.read_log("telegram_123") == ""

    def test_append_log_creates_file(self):
        self.store.ensure_dirs()
        self.store.append_log("telegram_123", "removed: old fact")
        content = (Path(self.tmp) / "users" / "telegram_123_log.md").read_text(encoding="utf-8")
        assert "removed: old fact" in content

    def test_append_log_appends_to_existing(self):
        self.store.ensure_dirs()
        self.store.append_log("telegram_123", "first")
        self.store.append_log("telegram_123", "second")
        content = (Path(self.tmp) / "users" / "telegram_123_log.md").read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content

    def test_line_count_returns_zero_for_new_user(self):
        self.store.ensure_dirs()
        assert self.store.line_count("telegram_123") == 0

    def test_line_count_returns_correct_count(self):
        self.store.ensure_dirs()
        (Path(self.tmp) / "users" / "telegram_123.md").write_text("line1\nline2\nline3", encoding="utf-8")
        assert self.store.line_count("telegram_123") == 3


# ---------------------------------------------------------------------------
# MemoryClassifier
# ---------------------------------------------------------------------------

class TestMemoryClassifier:
    def setup_method(self):
        from src.mmd import MemoryClassifier
        self.mock_llm = Mock()
        self.classifier = MemoryClassifier(llm=self.mock_llm)

    def test_classify_returns_ops_from_llm(self):
        self.mock_llm.complete_structured.return_value = Mock(
            parsed={"private": [{"op": "ADD", "content": "用戶喜歡 Python"}]}
        )
        result = self.classifier.classify([("I like Python", "Great!")], "")
        assert result == [{"op": "ADD", "content": "用戶喜歡 Python"}]

    def test_classify_returns_empty_list_on_none_response(self):
        self.mock_llm.complete_structured.return_value = Mock(parsed=None)
        result = self.classifier.classify([("hello", "hi")], "")
        assert result == []

    def test_classify_returns_empty_list_on_exception(self):
        self.mock_llm.complete_structured.side_effect = RuntimeError("LLM error")
        result = self.classifier.classify([("hello", "hi")], "")
        assert result == []

    def test_classify_passes_current_memory_to_llm(self):
        self.mock_llm.complete_structured.return_value = Mock(parsed={"private": []})
        self.classifier.classify([("hello", "hi")], "existing memory content")
        call_kwargs = self.mock_llm.complete_structured.call_args.kwargs
        assert "existing memory content" in call_kwargs["instructions"]

    def test_classify_passes_turns_to_llm(self):
        self.mock_llm.complete_structured.return_value = Mock(parsed={"private": []})
        self.classifier.classify([("user says this", "assistant says that")], "")
        call_kwargs = self.mock_llm.complete_structured.call_args.kwargs
        input_text = call_kwargs["input"][0]["text"]
        assert "user says this" in input_text


# ---------------------------------------------------------------------------
# MemoryCompactor
# ---------------------------------------------------------------------------

class TestMemoryCompactor:
    def setup_method(self):
        from src.mmd import MemoryCompactor
        self.mock_llm = Mock()
        self.compactor = MemoryCompactor(llm=self.mock_llm)

    def test_compact_returns_compacted_and_summary(self):
        self.mock_llm.complete_structured.return_value = Mock(
            parsed={"compacted": "# Memory\n- kept fact", "removed_summary": "removed: old fact"}
        )
        compacted, summary = self.compactor.compact("long content")
        assert compacted == "# Memory\n- kept fact"
        assert summary == "removed: old fact"

    def test_compact_returns_original_on_none_response(self):
        self.mock_llm.complete_structured.return_value = Mock(parsed=None)
        compacted, summary = self.compactor.compact("original content")
        assert compacted == "original content"
        assert summary == ""

    def test_compact_returns_original_on_exception(self):
        self.mock_llm.complete_structured.side_effect = RuntimeError("LLM error")
        compacted, summary = self.compactor.compact("original content")
        assert compacted == "original content"
        assert summary == ""


# ---------------------------------------------------------------------------
# _apply_ops (pure function)
# ---------------------------------------------------------------------------

class TestApplyOps:
    def setup_method(self):
        from src.mmd import _apply_ops
        self.apply = _apply_ops

    def test_add_appends_new_line(self):
        result = self.apply("# Memory\n", [{"op": "ADD", "content": "新事實"}])
        assert "新事實" in result

    def test_delete_removes_line(self):
        result = self.apply("# Memory\n- 舊事實\n", [{"op": "DELETE", "content": "舊事實"}])
        assert "舊事實" not in result

    def test_update_replaces_old_with_new(self):
        result = self.apply("# Memory\n- 舊事實\n", [{"op": "UPDATE", "old": "舊事實", "content": "新事實"}])
        assert "新事實" in result
        assert "舊事實" not in result

    def test_noop_leaves_content_unchanged(self):
        original = "# Memory\n- fact\n"
        result = self.apply(original, [{"op": "NOOP", "content": ""}])
        assert result == original

    def test_multiple_ops_applied_in_order(self):
        result = self.apply(
            "# Memory\n- fact A\n",
            [
                {"op": "DELETE", "content": "fact A"},
                {"op": "ADD", "content": "fact B"},
            ],
        )
        assert "fact A" not in result
        assert "fact B" in result


# ---------------------------------------------------------------------------
# MMDProvider
# ---------------------------------------------------------------------------

class TestMMDProvider:
    def setup_method(self):
        from src.mmd import MMDProvider
        self.ctx = Mock()
        self.store = Mock()
        self.classifier = Mock()
        self.compactor = Mock()
        self.store.is_available.return_value = True
        self.store.read_memory.return_value = ""
        self.store.read_log.return_value = ""
        self.store.line_count.return_value = 0
        self.classifier.classify.return_value = []
        self.compactor.compact.return_value = ("compacted", "removed")
        self.provider = MMDProvider(self.store, self.classifier, self.compactor)

    # --- basic interface ---

    def test_name_returns_mmd(self):
        assert self.provider.name == "mmd"

    def test_is_available_delegates_to_store(self):
        self.store.is_available.return_value = True
        assert self.provider.is_available() is True
        self.store.is_available.return_value = False
        assert self.provider.is_available() is False

    # --- initialize ---

    def test_initialize_calls_ensure_dirs(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.ensure_dirs.assert_called_once()

    def test_initialize_stores_session_user_mapping(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.prefetch("q", session_id="sess_1")
        self.store.read_memory.assert_called_with("telegram_123")

    def test_initialize_without_user_id_raises(self):
        with pytest.raises(KeyError):
            self.provider.initialize("sess_1")

    # --- prefetch ---

    def test_prefetch_returns_memory_file_contents(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_memory.return_value = "# Memory\n- fact"
        assert self.provider.prefetch("q", session_id="sess_1") == "# Memory\n- fact"

    def test_prefetch_returns_empty_for_unknown_session(self):
        assert self.provider.prefetch("q", session_id="unknown") == ""

    # --- sync_turn ---

    def test_sync_turn_buffers_turns(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.provider.sync_turn("bye", "goodbye", session_id="sess_1")
        self.provider.on_session_end([])
        turns = self.classifier.classify.call_args[0][0]
        assert len(turns) == 2
        assert turns[0] == ("hello", "hi")
        assert turns[1] == ("bye", "goodbye")

    def test_sync_turn_ignores_unknown_session(self):
        # Should not raise
        self.provider.sync_turn("hello", "hi", session_id="unknown")

    # --- on_session_end ---

    def test_on_session_end_noop_when_buffer_empty(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.on_session_end([])
        self.classifier.classify.assert_not_called()

    def test_on_session_end_triggers_extract_when_buffer_nonempty(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.provider.on_session_end([])
        self.classifier.classify.assert_called_once()

    def test_on_session_end_cleans_up_session(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.on_session_end([])
        # After cleanup, prefetch returns empty
        assert self.provider.prefetch("q", session_id="sess_1") == ""

    # --- extract and persist ---

    def test_extract_applies_add_op(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("I like Python", "Great!", session_id="sess_1")
        self.store.read_memory.return_value = "# Memory\n"
        self.classifier.classify.return_value = [{"op": "ADD", "content": "用戶喜歡 Python"}]
        self.provider.on_session_end([])
        written = self.store.write_memory.call_args[0][1]
        assert "用戶喜歡 Python" in written

    def test_extract_applies_delete_op(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("I no longer like Java", "OK", session_id="sess_1")
        self.store.read_memory.return_value = "# Memory\n- 用戶喜歡 Java\n"
        self.classifier.classify.return_value = [{"op": "DELETE", "content": "用戶喜歡 Java"}]
        self.provider.on_session_end([])
        written = self.store.write_memory.call_args[0][1]
        assert "用戶喜歡 Java" not in written

    def test_extract_noop_does_not_write(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.store.read_memory.return_value = "# Memory\n- fact"
        self.classifier.classify.return_value = [{"op": "NOOP", "content": ""}]
        self.provider.on_session_end([])
        self.store.write_memory.assert_not_called()

    def test_extract_invalid_llm_response_does_not_crash(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.classifier.classify.return_value = []
        self.provider.on_session_end([])  # should not raise

    def test_buffer_cleared_after_extract(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.provider.on_session_end([])
        # Re-initialize same session
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.on_session_end([])
        # classify should NOT be called again (buffer was empty)
        assert self.classifier.classify.call_count == 1

    # --- compact ---

    def test_compact_triggered_when_updated_content_exceeds_200_lines(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        long_memory = "\n".join([f"- fact {i}" for i in range(200)])
        self.store.read_memory.return_value = long_memory
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        self.provider.on_session_end([])
        self.compactor.compact.assert_called_once()

    def test_compact_not_triggered_when_under_200_lines(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.store.read_memory.return_value = "# Memory\n- fact\n"
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        self.provider.on_session_end([])
        self.compactor.compact.assert_not_called()

    def test_compact_writes_compacted_content(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        long_memory = "\n".join([f"- fact {i}" for i in range(200)])
        self.store.read_memory.return_value = long_memory
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        self.compactor.compact.return_value = ("compacted content", "removed stuff")
        self.provider.on_session_end([])
        self.store.write_memory.assert_called_with("telegram_123", "compacted content")

    def test_compact_appends_summary_to_log(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        long_memory = "\n".join([f"- fact {i}" for i in range(200)])
        self.store.read_memory.return_value = long_memory
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        self.compactor.compact.return_value = ("compacted", "removed stuff")
        self.provider.on_session_end([])
        self.store.append_log.assert_called_with("telegram_123", "removed stuff")

    def test_compact_skips_log_when_summary_empty(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        long_memory = "\n".join([f"- fact {i}" for i in range(200)])
        self.store.read_memory.return_value = long_memory
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        self.compactor.compact.return_value = ("compacted", "")
        self.provider.on_session_end([])
        self.store.append_log.assert_not_called()

    # --- tools ---

    def test_get_tool_schemas_includes_load_deep_memory(self):
        schemas = self.provider.get_tool_schemas()
        names = [s["name"] for s in schemas]
        assert "load_deep_memory" in names

    def test_handle_tool_call_returns_log_contents(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_log.return_value = "old archived memories"
        result = self.provider.handle_tool_call("load_deep_memory", {}, session_id="sess_1")
        assert result == "old archived memories"

    def test_handle_tool_call_returns_placeholder_for_empty_log(self):
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_log.return_value = ""
        result = self.provider.handle_tool_call("load_deep_memory", {}, session_id="sess_1")
        assert "empty" in result.lower() or result  # graceful response

    def test_handle_unknown_tool_returns_message(self):
        result = self.provider.handle_tool_call("unknown_tool", {})
        assert "unknown" in result.lower()


# ---------------------------------------------------------------------------
# /mmd slash command
# ---------------------------------------------------------------------------

class TestMmdCommand:
    def setup_method(self):
        import src.mmd as mmd_module
        from src.mmd import MMDProvider
        self.mmd_module = mmd_module
        self.store = Mock()
        self.classifier = Mock()
        self.compactor = Mock()
        self.store.is_available.return_value = True
        self.store.read_memory.return_value = ""
        self.store.read_log.return_value = ""
        self.classifier.classify.return_value = []
        self.compactor.compact.return_value = ("compacted", "removed")
        self.provider = MMDProvider(self.store, self.classifier, self.compactor)
        mmd_module._active_provider = self.provider

    def teardown_method(self):
        self.mmd_module._active_provider = None

    def test_show_returns_memory_contents(self):
        from src.mmd import _mmd_command
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_memory.return_value = "- fact A\n- fact B"
        result = _mmd_command("show")
        assert "fact A" in result

    def test_show_empty_memory(self):
        from src.mmd import _mmd_command
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_memory.return_value = ""
        result = _mmd_command("show")
        assert "empty" in result.lower()

    def test_no_args_same_as_show(self):
        from src.mmd import _mmd_command
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.store.read_memory.return_value = "- fact"
        assert _mmd_command("") == _mmd_command("show")

    def test_show_no_active_session(self):
        from src.mmd import _mmd_command
        result = _mmd_command("show")
        assert "session" in result.lower()

    def test_flush_triggers_extract(self):
        from src.mmd import _mmd_command
        self.provider.initialize("sess_1", user_id="telegram_123")
        self.provider.sync_turn("hello", "hi", session_id="sess_1")
        self.classifier.classify.return_value = [{"op": "ADD", "content": "new fact"}]
        result = _mmd_command("flush")
        assert "flushed" in result.lower()
        self.classifier.classify.assert_called_once()

    def test_flush_empty_buffer(self):
        from src.mmd import _mmd_command
        self.provider.initialize("sess_1", user_id="telegram_123")
        result = _mmd_command("flush")
        assert "nothing" in result.lower()

    def test_unknown_subcommand_shows_help(self):
        from src.mmd import _mmd_command
        result = _mmd_command("unknown")
        assert "show" in result and "flush" in result

    def test_no_provider_returns_not_initialized(self):
        from src.mmd import _mmd_command
        self.mmd_module._active_provider = None
        result = _mmd_command("show")
        assert "not initialized" in result.lower()
