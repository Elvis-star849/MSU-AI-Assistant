"""Hashing and crash-safe file operations (write to a temporary file, flush to disk, then atomically replace)."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

# Test hook: called with a step name at each crash-relevant point; tests replace it to simulate a crash.
crash_point: Callable[[str], None] = lambda step: None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes (sorted keys, UTF-8, LF) used for hashing and for files that are hashed."""
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def retry(op: Callable[[], Any], retries: int = 8, delay_s: float = 0.25) -> Any:
    """Retry an operation that can fail while Windows, OneDrive or an antivirus briefly holds a file."""
    for attempt in range(retries + 1):
        try:
            return op()
        except PermissionError:
            if attempt == retries:
                raise
            time.sleep(delay_s * (attempt + 1))


def fsync_file(path: Path) -> None:
    with open(path, "rb+") as f:
        os.fsync(f.fileno())


def atomic_write_bytes(path: Path, data: bytes, retries: int = 8, delay_s: float = 0.25) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    retry(lambda: os.replace(tmp, path), retries, delay_s)


def atomic_write_json(path: Path, obj: Any, **kw) -> None:
    atomic_write_bytes(path, canonical_json(obj), **kw)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rename_dir(src: Path, dst: Path, retries: int = 8, delay_s: float = 0.25) -> None:
    if Path(dst).exists():
        raise FileExistsError(dst)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    retry(lambda: os.rename(src, dst), retries, delay_s)
