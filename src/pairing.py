"""Cross-channel user pairing module (ADR-0009).

Storage layout (relative to data_dir):
    _pairing/{code}.json   — short-lived pairing request
    identity.json          — canonical channel-to-name mapping
    identity.lock          — file lock for atomic identity update
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import string
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PairingError(Exception):
    """Base class for all pairing errors."""


class CodeNotFound(PairingError):
    """No active pairing request exists for the given code."""


class CodeExpired(PairingError):
    """The pairing code existed but its TTL has elapsed."""


class TooManyAttempts(PairingError):
    """The code was guessed incorrectly too many times and is now locked."""


class AlreadyPaired(PairingError):
    """The confirming channel ID is already paired under some canonical name."""


class ActiveRequestExists(PairingError):
    """The initiating channel already has an unexpired pairing request."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LEN = 6
_TTL_SECONDS = 600          # 10 minutes
_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# PairingManager
# ---------------------------------------------------------------------------

class PairingManager:
    """Manages cross-channel identity pairing.

    All public methods are synchronous and safe to call from a single process.
    The file lock on identity.json is a defensive measure for future
    multi-process scaling.
    """

    def __init__(self, data_dir: str) -> None:
        self._root = Path(data_dir)
        self._pairing_dir = self._root / "_pairing"
        self._identity_path = self._root / "identity.json"
        self._lock_path = self._root / "identity.lock"

        self._pairing_dir.mkdir(parents=True, exist_ok=True)
        self._root.mkdir(parents=True, exist_ok=True)

        # Remove orphaned .tmp files left by a crashed atomic write.
        tmp = self._identity_path.with_suffix(".json.tmp")
        if tmp.exists():
            tmp.unlink()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_request(self, initiator_id: str) -> str:
        """Generate a pairing code for *initiator_id* and persist the request.

        Raises ActiveRequestExists if *initiator_id* already has an
        unexpired, non-exhausted pairing request outstanding.

        Returns the 6-character code (uppercase).
        """
        self._assert_no_active_request(initiator_id)

        code = self._generate_code()
        expires_at = _utcnow_plus(_TTL_SECONDS)
        payload = {
            "code": code,
            "initiator_id": initiator_id,
            "expires_at": expires_at,
            "attempts": 0,
        }
        self._write_pairing(code, payload)
        return code

    def confirm(self, confirmer_id: str, code: str) -> tuple[str, list[str], list[str]]:
        """Confirm a pairing request from a different channel.

        *confirmer_id* is the channel ID of the user who received the code and
        is now submitting it.  *code* is case-insensitive.

        Returns (canonical_name, merged_ids, memory_files_to_merge) where:
          - *canonical_name* is the key stored in identity.json (always initiator_id).
          - *merged_ids* is the full list of channel IDs now linked under that name.
          - *memory_files_to_merge* lists the .md file paths the caller must merge
            via LLM into canonical_name.md (empty list if nothing to merge).

        The actual LLM-based memory file merge is the caller's responsibility.

        Raises:
            PairingError    — self-confirm attempt.
            CodeNotFound    — no matching request file.
            CodeExpired     — TTL elapsed.
            TooManyAttempts — attempts >= MAX_ATTEMPTS.
            AlreadyPaired   — confirmer_id is already registered.
        """
        code = code.upper()
        payload = self._load_pairing(code)  # raises CodeNotFound

        if confirmer_id == payload["initiator_id"]:
            raise PairingError("Cannot confirm your own pairing request")

        # Expiry check
        if _is_expired(payload["expires_at"]):
            self._delete_pairing(code)
            raise CodeExpired(f"Code {code} expired at {payload['expires_at']}")

        # Attempt-cap check (before incrementing so the counter tracks *failed*
        # attempts, consistent with the spec: "increment on each failed confirm attempt")
        if payload["attempts"] >= _MAX_ATTEMPTS:
            raise TooManyAttempts(
                f"Code {code} exceeded {_MAX_ATTEMPTS} failed attempts"
            )

        initiator_id: str = payload["initiator_id"]

        # Atomic identity update
        lock_fd = open(self._lock_path, "w")  # noqa: SIM115  — need explicit close
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            identity = self._read_identity()

            # Check confirmer is not already paired
            for canonical, ids in identity.items():
                if confirmer_id in ids:
                    # Increment attempts because confirmer is wrong identity
                    payload["attempts"] += 1
                    self._write_pairing(code, payload)
                    raise AlreadyPaired(
                        f"{confirmer_id} is already paired as '{canonical}'"
                    )

            # Determine canonical name and merge
            canonical_name, merged_ids = _merge(
                identity, initiator_id, confirmer_id
            )
            identity[canonical_name] = merged_ids

            # Write to .tmp then rename (atomic on same filesystem)
            tmp = self._identity_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(identity, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp.rename(self._identity_path)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

        self._delete_pairing(code)

        # Identify memory files that need LLM merging by the caller.
        users_dir = self._root / "users"
        memory_files_to_merge: list[str] = []
        for cid in merged_ids:
            path = users_dir / f"{cid}.md"
            if path.exists() and cid != canonical_name:
                memory_files_to_merge.append(str(path))

        return canonical_name, merged_ids, memory_files_to_merge

    def cleanup_expired(self) -> None:
        """Delete all expired _pairing/*.json files."""
        for path in self._pairing_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if _is_expired(data.get("expires_at", "")):
                    path.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                # Corrupt or already-deleted file — skip silently.
                pass

    def resolve(self, channel_id: str) -> str:
        """Return the canonical name for *channel_id*, or *channel_id* if unpaired."""
        identity = self._read_identity()
        for canonical, ids in identity.items():
            if channel_id in ids:
                return canonical
        return channel_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_no_active_request(self, initiator_id: str) -> None:
        """Raise ActiveRequestExists if *initiator_id* has a live request."""
        for path in self._pairing_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if (
                data.get("initiator_id") == initiator_id
                and not _is_expired(data.get("expires_at", ""))
                and data.get("attempts", 0) < _MAX_ATTEMPTS
            ):
                raise ActiveRequestExists(
                    f"{initiator_id} already has an active pairing request "
                    f"(code {data['code']}, expires {data['expires_at']})"
                )

    def _generate_code(self) -> str:
        """Return a random 6-char uppercase alphanumeric code, guaranteed unique."""
        for _ in range(100):
            code = "".join(random.choices(_CODE_CHARS, k=_CODE_LEN))
            if not self._pairing_path(code).exists():
                return code
        raise RuntimeError("Could not generate a unique pairing code after 100 tries")

    def _pairing_path(self, code: str) -> Path:
        return self._pairing_dir / f"{code}.json"

    def _write_pairing(self, code: str, payload: dict) -> None:
        self._pairing_path(code).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_pairing(self, code: str) -> dict:
        path = self._pairing_path(code)
        if not path.exists():
            raise CodeNotFound(f"No pairing request for code {code}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CodeNotFound(f"Corrupt pairing file for code {code}") from exc

    def _delete_pairing(self, code: str) -> None:
        self._pairing_path(code).unlink(missing_ok=True)

    def _read_identity(self) -> dict[str, list[str]]:
        if not self._identity_path.exists():
            return {}
        try:
            return json.loads(self._identity_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _utcnow_plus(seconds: int) -> str:
    """Return an ISO-8601 UTC timestamp *seconds* from now."""
    from datetime import timedelta
    dt = datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_expired(expires_at: str) -> bool:
    """Return True if the ISO-8601 UTC string is in the past."""
    try:
        dt = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        return datetime.now(tz=timezone.utc) >= dt
    except ValueError:
        # Unparseable → treat as expired to be safe.
        return True


def _merge(
    identity: dict[str, list[str]],
    initiator_id: str,
    confirmer_id: str,
) -> tuple[str, list[str]]:
    """Determine the canonical name and merged ID list for the pairing.

    If either party is already in identity.json, their existing canonical name
    wins (initiator takes priority if both are already present).  Otherwise the
    initiator_id becomes the canonical name.
    """
    initiator_canonical: str | None = None
    confirmer_canonical: str | None = None

    for canonical, ids in identity.items():
        if initiator_id in ids:
            initiator_canonical = canonical
        if confirmer_id in ids:
            confirmer_canonical = canonical

    if initiator_canonical:
        canonical_name = initiator_canonical
        base_ids: list[str] = list(identity[canonical_name])
        # Absorb confirmer's existing group if it exists
        if confirmer_canonical and confirmer_canonical != canonical_name:
            base_ids.extend(identity[confirmer_canonical])
            del identity[confirmer_canonical]
        elif confirmer_id not in base_ids:
            base_ids.append(confirmer_id)
    elif confirmer_canonical:
        canonical_name = confirmer_canonical
        base_ids = list(identity[canonical_name])
        if initiator_id not in base_ids:
            base_ids.append(initiator_id)
    else:
        # Neither party is known yet — use initiator_id as canonical name.
        canonical_name = initiator_id
        base_ids = [initiator_id, confirmer_id]

    # Deduplicate while preserving order.
    seen: set[str] = set()
    merged: list[str] = []
    for item in base_ids:
        if item not in seen:
            seen.add(item)
            merged.append(item)

    return canonical_name, merged
