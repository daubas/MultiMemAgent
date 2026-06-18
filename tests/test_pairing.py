"""
TDD tests for src/pairing.py and pairing integration in MMDProvider.

Structure:
  TestPairingManagerResolve     — UUID auto-registration
  TestPairingManagerCreateRequest — code generation and duplicate guard
  TestPairingManagerConfirm     — happy path, error cases, memory merge hints
  TestPairingManagerCleanup     — expired token cleanup
  TestMMDProviderPairingWiring  — MMDProvider uses UUID keys, /pair command
"""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pairing import (
    PairingManager,
    PairingError,
    CodeNotFound,
    CodeExpired,
    TooManyAttempts,
    AlreadyPaired,
    ActiveRequestExists,
    _merge,
    _utcnow_plus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path=None):
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    return PairingManager(tmp_path), tmp_path


def _expired_ts():
    dt = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _future_ts(seconds=600):
    return _utcnow_plus(seconds)


# ---------------------------------------------------------------------------
# TestPairingManagerResolve
# ---------------------------------------------------------------------------

class TestPairingManagerResolve:
    def test_resolve_new_user_creates_uuid(self):
        mgr, _ = _make_manager()
        result = mgr.resolve("user_A")
        assert result != "user_A"
        assert len(result) == 36  # UUID format

    def test_resolve_same_user_returns_same_uuid(self):
        mgr, _ = _make_manager()
        first = mgr.resolve("user_A")
        second = mgr.resolve("user_A")
        assert first == second

    def test_resolve_different_users_get_different_uuids(self):
        mgr, _ = _make_manager()
        uuid_a = mgr.resolve("user_A")
        uuid_b = mgr.resolve("user_B")
        assert uuid_a != uuid_b

    def test_resolve_persists_to_identity_file(self):
        mgr, tmp = _make_manager()
        uuid_key = mgr.resolve("user_A")
        identity_path = Path(tmp) / "identity.json"
        assert identity_path.exists()
        data = json.loads(identity_path.read_text())
        assert uuid_key in data
        assert "user_A" in data[uuid_key]

    def test_resolve_after_pairing_returns_canonical_uuid(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        canonical, _, _ = mgr.confirm("user_B", code)
        assert mgr.resolve("user_A") == canonical
        assert mgr.resolve("user_B") == canonical


# ---------------------------------------------------------------------------
# TestPairingManagerCreateRequest
# ---------------------------------------------------------------------------

class TestPairingManagerCreateRequest:
    def test_returns_six_char_uppercase_code(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        assert len(code) == 6
        assert code.isupper() or code.isalnum()

    def test_code_persisted_to_disk(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        assert pairing_file.exists()

    def test_active_request_exists_raises_on_second_call(self):
        mgr, _ = _make_manager()
        mgr.create_request("user_A")
        with pytest.raises(ActiveRequestExists):
            mgr.create_request("user_A")

    def test_expired_request_allows_new_create(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        # Manually expire the request
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        data = json.loads(pairing_file.read_text())
        data["expires_at"] = _expired_ts()
        pairing_file.write_text(json.dumps(data))
        # Should not raise
        new_code = mgr.create_request("user_A")
        assert new_code != code

    def test_exhausted_request_allows_new_create(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        data = json.loads(pairing_file.read_text())
        data["attempts"] = 3
        pairing_file.write_text(json.dumps(data))
        new_code = mgr.create_request("user_A")
        assert new_code != code


# ---------------------------------------------------------------------------
# TestPairingManagerConfirm
# ---------------------------------------------------------------------------

class TestPairingManagerConfirm:
    def test_happy_path_returns_uuid_canonical(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        canonical, merged_ids, files = mgr.confirm("user_B", code)
        assert len(canonical) == 36  # UUID
        assert "user_A" in merged_ids
        assert "user_B" in merged_ids
        assert files == []

    def test_both_users_resolve_to_same_uuid_after_pairing(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        canonical, _, _ = mgr.confirm("user_B", code)
        assert mgr.resolve("user_A") == canonical
        assert mgr.resolve("user_B") == canonical

    def test_pairing_code_deleted_on_success(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        mgr.confirm("user_B", code)
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        assert not pairing_file.exists()

    def test_returns_memory_file_to_merge_when_confirmer_has_memory(self):
        mgr, tmp = _make_manager()
        # Both users already have UUIDs (simulates existing users).
        # Initiator wins, so confirmer's old UUID file must be merged in.
        uuid_a = mgr.resolve("user_A")  # initiator gets UUID first
        uuid_b = mgr.resolve("user_B")  # confirmer gets UUID
        mem_file = Path(tmp) / "users" / f"{uuid_b}.md"
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        mem_file.write_text("- user_B memory\n")

        code = mgr.create_request("user_A")
        canonical, _, files = mgr.confirm("user_B", code)

        # Initiator (user_A / uuid_a) wins; confirmer's old uuid_b file is returned
        assert canonical == uuid_a
        assert len(files) == 1
        assert files[0] == str(mem_file)

    def test_returns_log_file_to_merge_when_confirmer_has_deep_memory(self):
        mgr, tmp = _make_manager()
        uuid_a = mgr.resolve("user_A")
        uuid_b = mgr.resolve("user_B")
        log_file = Path(tmp) / "users" / f"{uuid_b}_log.md"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("archived user_B memory\n")

        code = mgr.create_request("user_A")
        canonical, _, files = mgr.confirm("user_B", code)

        assert canonical == uuid_a
        assert str(log_file) in files

    def test_no_memory_file_when_confirmer_has_no_file(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        _, _, files = mgr.confirm("user_B", code)
        assert files == []

    def test_self_confirm_raises(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        with pytest.raises(PairingError):
            mgr.confirm("user_A", code)

    def test_code_not_found_raises(self):
        mgr, _ = _make_manager()
        with pytest.raises(CodeNotFound):
            mgr.confirm("user_B", "XXXXXX")

    def test_repeated_invalid_codes_lock_confirmer(self):
        mgr, _ = _make_manager()
        for _ in range(3):
            with pytest.raises(CodeNotFound):
                mgr.confirm("user_B", "XXXXXX")
        with pytest.raises(TooManyAttempts):
            mgr.confirm("user_B", "XXXXXX")

    def test_successful_confirm_clears_failed_attempts(self):
        mgr, _ = _make_manager()
        with pytest.raises(CodeNotFound):
            mgr.confirm("user_B", "XXXXXX")

        code = mgr.create_request("user_A")
        mgr.confirm("user_B", code)

        code2 = mgr.create_request("user_C")
        canonical, merged_ids, _ = mgr.confirm("user_B", code2)
        assert "user_B" in merged_ids

    def test_expired_code_raises(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        data = json.loads(pairing_file.read_text())
        data["expires_at"] = _expired_ts()
        pairing_file.write_text(json.dumps(data))
        with pytest.raises(CodeExpired):
            mgr.confirm("user_B", code)

    def test_too_many_attempts_raises(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        data = json.loads(pairing_file.read_text())
        data["attempts"] = 3
        pairing_file.write_text(json.dumps(data))
        with pytest.raises(TooManyAttempts):
            mgr.confirm("user_B", code)

    def test_already_paired_same_group_raises(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        mgr.confirm("user_B", code)
        # Try to pair again
        code2 = mgr.create_request("user_A")
        with pytest.raises(AlreadyPaired):
            mgr.confirm("user_B", code2)

    def test_case_insensitive_code(self):
        mgr, _ = _make_manager()
        code = mgr.create_request("user_A")
        canonical, merged_ids, _ = mgr.confirm("user_B", code.lower())
        assert "user_A" in merged_ids

    def test_initiator_uuid_wins_when_initiator_already_has_uuid(self):
        mgr, _ = _make_manager()
        # Ensure user_A already has a UUID
        uuid_a = mgr.resolve("user_A")
        code = mgr.create_request("user_A")
        canonical, _, _ = mgr.confirm("user_B", code)
        assert canonical == uuid_a


# ---------------------------------------------------------------------------
# TestPairingManagerCleanup
# ---------------------------------------------------------------------------

class TestPairingManagerCleanup:
    def test_cleanup_removes_expired_files(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"
        data = json.loads(pairing_file.read_text())
        data["expires_at"] = _expired_ts()
        pairing_file.write_text(json.dumps(data))

        mgr.cleanup_expired()
        assert not pairing_file.exists()

    def test_cleanup_keeps_valid_files(self):
        mgr, tmp = _make_manager()
        code = mgr.create_request("user_A")
        pairing_file = Path(tmp) / "_pairing" / f"{code}.json"

        mgr.cleanup_expired()
        assert pairing_file.exists()


# ---------------------------------------------------------------------------
# TestMergeFunction
# ---------------------------------------------------------------------------

class TestMergeFunction:
    def test_both_unknown_generates_uuid(self):
        identity = {}
        canonical, merged = _merge(identity, "A", "B")
        assert len(canonical) == 36  # UUID
        assert "A" in merged
        assert "B" in merged

    def test_initiator_known_uses_initiator_canonical(self):
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000000"
        identity = {uuid_a: ["A"]}
        canonical, merged = _merge(identity, "A", "B")
        assert canonical == uuid_a
        assert "B" in merged

    def test_confirmer_known_uses_confirmer_canonical(self):
        uuid_b = "bbbbbbbb-0000-0000-0000-000000000000"
        identity = {uuid_b: ["B"]}
        canonical, merged = _merge(identity, "A", "B")
        assert canonical == uuid_b
        assert "A" in merged

    def test_both_known_initiator_wins(self):
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000000"
        uuid_b = "bbbbbbbb-0000-0000-0000-000000000000"
        identity = {uuid_a: ["A"], uuid_b: ["B"]}
        canonical, merged = _merge(identity, "A", "B")
        assert canonical == uuid_a
        assert "B" in merged
        assert uuid_b not in identity  # confirmer's old entry removed

    def test_deduplication(self):
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000000"
        identity = {uuid_a: ["A", "B"]}
        canonical, merged = _merge(identity, "A", "B")
        assert merged.count("A") == 1
        assert merged.count("B") == 1


# ---------------------------------------------------------------------------
# TestMMDProviderPairingWiring
# ---------------------------------------------------------------------------

class TestMMDProviderPairingWiring:
    def _make_provider(self, tmp_path):
        from src.mmd import MemoryStore, MemoryClassifier, MemoryCompactor, MMDProvider, IdleFlushScheduler
        store = MemoryStore(Path(tmp_path))
        store.ensure_dirs()
        classifier = Mock(spec=MemoryClassifier)
        classifier.classify.return_value = []
        compactor = Mock(spec=MemoryCompactor)
        scheduler = Mock(spec=IdleFlushScheduler)
        pairing = PairingManager(tmp_path)
        return MMDProvider(store, classifier, compactor, scheduler, pairing_manager=pairing), store, pairing

    def test_initialize_resolves_uuid_for_user(self):
        tmp = tempfile.mkdtemp()
        provider, store, pairing = self._make_provider(tmp)
        provider.initialize("sess1", user_id="user_A")
        uuid_key = provider._sessions["sess1"]
        assert uuid_key != "user_A"
        assert len(uuid_key) == 36

    def test_memory_stored_under_uuid_not_user_id(self):
        tmp = tempfile.mkdtemp()
        provider, store, pairing = self._make_provider(tmp)
        provider.initialize("sess1", user_id="user_A")
        uuid_key = provider._sessions["sess1"]

        # Write something to uuid memory file directly
        (Path(tmp) / "users" / f"{uuid_key}.md").write_text("- test fact\n")

        result = provider.prefetch("query", session_id="sess1")
        assert "test fact" in result

    def test_user_id_stored_separately_from_uuid(self):
        tmp = tempfile.mkdtemp()
        provider, store, pairing = self._make_provider(tmp)
        provider.initialize("sess1", user_id="user_A")
        assert provider._user_ids["sess1"] == "user_A"
        assert provider._sessions["sess1"] != "user_A"

    def test_on_session_end_clears_user_id(self):
        tmp = tempfile.mkdtemp()
        provider, store, pairing = self._make_provider(tmp)
        provider.initialize("sess1", user_id="user_A")
        provider.on_session_end([])
        assert "sess1" not in provider._user_ids

    def test_paired_users_share_memory(self):
        tmp = tempfile.mkdtemp()
        provider, store, pairing = self._make_provider(tmp)

        # Pair user_A and user_B
        code = pairing.create_request("user_A")
        canonical, _, _ = pairing.confirm("user_B", code)

        # Both sessions should resolve to same UUID
        provider.initialize("sess_a", user_id="user_A")
        provider.initialize("sess_b", user_id="user_B")
        assert provider._sessions["sess_a"] == provider._sessions["sess_b"]
        assert provider._sessions["sess_a"] == canonical


class TestPairCommand:
    def _make_active_provider(self, tmp_path):
        import src.mmd as mmd_mod
        from src.mmd import MemoryStore, MemoryClassifier, MemoryCompactor, MMDProvider, IdleFlushScheduler
        store = MemoryStore(Path(tmp_path))
        store.ensure_dirs()
        classifier = Mock(spec=MemoryClassifier)
        classifier.classify.return_value = []
        compactor = Mock(spec=MemoryCompactor)
        scheduler = Mock(spec=IdleFlushScheduler)
        pairing = PairingManager(tmp_path)
        provider = MMDProvider(store, classifier, compactor, scheduler, pairing_manager=pairing)
        provider.initialize("sess1", user_id="user_A")
        mmd_mod._active_provider = provider
        return provider, pairing, mmd_mod

    def test_pair_command_no_args_returns_code(self):
        tmp = tempfile.mkdtemp()
        provider, pairing, mmd_mod = self._make_active_provider(tmp)
        from src.mmd import _pair_command
        result = _pair_command("")
        assert "配對碼" in result
        assert "6" in str(len(result.split("**")[1]))  # code is in bold

    def test_pair_command_confirms_pairing(self):
        tmp = tempfile.mkdtemp()
        provider, pairing, mmd_mod = self._make_active_provider(tmp)

        # user_B initiates a pairing request via PairingManager directly
        code = pairing.create_request("user_B")

        # user_A (the active session) confirms it
        from src.mmd import _pair_command
        result = _pair_command(code)
        assert "配對成功" in result
        assert "user_A" in result
        assert "user_B" in result

    def test_pair_command_invalid_code(self):
        tmp = tempfile.mkdtemp()
        provider, pairing, mmd_mod = self._make_active_provider(tmp)
        from src.mmd import _pair_command
        result = _pair_command("XXXXXX")
        assert "(pair:" in result

    def test_pair_command_no_session(self):
        import src.mmd as mmd_mod
        from src.mmd import MemoryStore, MemoryClassifier, MemoryCompactor, MMDProvider, IdleFlushScheduler
        tmp = tempfile.mkdtemp()
        store = MemoryStore(Path(tmp))
        classifier = Mock(spec=MemoryClassifier)
        compactor = Mock(spec=MemoryCompactor)
        scheduler = Mock(spec=IdleFlushScheduler)
        pairing = PairingManager(tmp)
        provider = MMDProvider(store, classifier, compactor, scheduler, pairing_manager=pairing)
        mmd_mod._active_provider = provider
        from src.mmd import _pair_command
        result = _pair_command("")
        assert "no active session" in result

    def test_pair_command_merges_memory_files(self):
        tmp = tempfile.mkdtemp()
        provider, pairing, mmd_mod = self._make_active_provider(tmp)

        # user_A's UUID was created by initialize() inside _make_active_provider
        uuid_a = provider._sessions["sess1"]
        # Write memory for user_A (the confirmer — will be absorbed into user_B's UUID)
        mem_a = Path(tmp) / "users" / f"{uuid_a}.md"
        mem_a.write_text("- user_A memory\n")

        # user_B initiates pairing — user_B's UUID will become canonical
        uuid_b = pairing.resolve("user_B")
        code = pairing.create_request("user_B")

        from src.mmd import _pair_command
        result = _pair_command(code)  # user_A confirms
        assert "配對成功" in result

        # user_A's old memory file should be absorbed (deleted)
        assert not mem_a.exists()

        # Canonical (user_B's UUID) should contain the merged content
        merged = (Path(tmp) / "users" / f"{uuid_b}.md").read_text()
        assert "user_A memory" in merged
