"""At-least-once delivery made exactly-once.

Meta retries a webhook until it sees a 2xx, and it retries whole batches, so
the same message id arrives more than once in normal operation. Every marker is
created with O_CREAT|O_EXCL, which is atomic on POSIX filesystems: two worker
processes racing on the same id cannot both win.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path


@dataclass(slots=True)
class DedupStore:
    path: Path
    ttl: timedelta = timedelta(days=2)
    prune_every: int = 200
    _since_prune: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.mkdir(parents=True, exist_ok=True)

    def _marker(self, key: str) -> Path:
        return self.path / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".seen")

    def seen_before(self, key: str) -> bool:
        """Claim the key. True means somebody already handled it."""
        try:
            self._marker(key).touch(exist_ok=False)
        except FileExistsError:
            return True
        self._since_prune += 1
        if self._since_prune >= self.prune_every:
            self.prune()
        return False

    def prune(self, now: float | None = None) -> int:
        """Drop markers older than the TTL so the directory stays small."""
        cutoff = (time.time() if now is None else now) - self.ttl.total_seconds()
        removed = 0
        for marker in self.path.glob("*.seen"):
            try:
                if marker.stat().st_mtime < cutoff:
                    marker.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        self._since_prune = 0
        return removed

    def release(self, key: str) -> None:
        """Give a key back so a redelivery or a manual replay can retry it."""
        self._marker(key).unlink(missing_ok=True)
