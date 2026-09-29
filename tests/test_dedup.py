"""Meta delivers at least once, so the store has to make it exactly once."""

from __future__ import annotations

import os
import time
from datetime import timedelta

from whatsapp_starter import DedupStore


def test_first_sighting_is_new_and_the_second_is_a_duplicate(dedup: DedupStore) -> None:
    assert dedup.seen_before("message:wamid.A") is False
    assert dedup.seen_before("message:wamid.A") is True
    assert dedup.seen_before("message:wamid.A") is True


def test_distinct_ids_do_not_collide(dedup: DedupStore) -> None:
    assert dedup.seen_before("message:wamid.A") is False
    assert dedup.seen_before("message:wamid.B") is False


def test_the_claim_survives_a_process_restart(tmp_path) -> None:
    assert DedupStore(tmp_path / "seen").seen_before("message:wamid.A") is False
    assert DedupStore(tmp_path / "seen").seen_before("message:wamid.A") is True


def test_a_released_key_can_be_retried(dedup: DedupStore) -> None:
    dedup.seen_before("message:wamid.A")
    dedup.release("message:wamid.A")
    assert dedup.seen_before("message:wamid.A") is False


def _backdate(store: DedupStore, days: int) -> None:
    stale = time.time() - timedelta(days=days).total_seconds()
    for marker in store.path.glob("*.seen"):
        os.utime(marker, (stale, stale))


def test_pruning_drops_expired_markers_only(tmp_path) -> None:
    store = DedupStore(tmp_path / "seen", ttl=timedelta(days=2))
    store.seen_before("old")
    _backdate(store, days=3)
    store.seen_before("fresh")

    assert store.prune() == 1
    assert store.seen_before("old") is False
    assert store.seen_before("fresh") is True


def test_pruning_runs_by_itself_once_enough_keys_arrived(tmp_path) -> None:
    store = DedupStore(tmp_path / "seen", ttl=timedelta(days=2), prune_every=2)
    store.seen_before("old")
    _backdate(store, days=3)
    store.seen_before("fresh")

    assert store.seen_before("old") is False
    assert store.seen_before("fresh") is True
