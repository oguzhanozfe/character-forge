"""Small shared helpers: hashing, atomic JSON, time stamps and errors."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class ForgeError(Exception):
    """A user-facing error. The CLI prints the message and exits with code 2."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path | str, value: Any) -> Path:
    """Atomic write with LF endings so a crash never leaves half a record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def write_text(path: Path | str, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def validate_id(identifier: str) -> str:
    if not ID_PATTERN.match(identifier or ""):
        raise ForgeError("Character id must be 1-48 chars of lowercase letters, digits, '-' or '_' (got %r)" % identifier)
    return identifier


def files_under(root: Path) -> Iterable[Path]:
    return sorted(p for p in Path(root).rglob("*") if p.is_file())


def relpath(path: Path, root: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
