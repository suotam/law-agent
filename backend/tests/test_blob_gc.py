"""Tests for the blob GC sweep."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from law_agent.storage import FilesystemBlobStore, sweep_blobs

ORPHAN = b"nobody references me"
SHARED = b"two documents point here"


def _age(store: FilesystemBlobStore, digest: str, *, hours: float) -> None:
    """Backdate a blob's mtime, so it falls outside the grace period."""
    target = store.path_for(digest)
    stale = target.stat().st_mtime - hours * 3600
    os.utime(target, (stale, stale))


def test_sweep_deletes_an_unreferenced_old_blob(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(ORPHAN)
    _age(store, digest, hours=48)

    stats = sweep_blobs(store, is_referenced=lambda _: False)

    assert stats.deleted == 1
    assert not store.exists(digest)


def test_sweep_keeps_a_referenced_blob(tmp_path: Path) -> None:
    """A blob shared by two documents must survive; the predicate is the truth."""
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(SHARED)
    _age(store, digest, hours=48)

    stats = sweep_blobs(store, is_referenced=lambda sha: sha == digest)

    assert stats.deleted == 0
    assert stats.kept_referenced == 1
    assert store.exists(digest)


def test_sweep_keeps_a_blob_younger_than_the_grace_period(tmp_path: Path) -> None:
    """Closes the window between an unreferenced check and a concurrent upload."""
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(ORPHAN)

    stats = sweep_blobs(store, is_referenced=lambda _: False)

    assert stats.deleted == 0
    assert stats.kept_young == 1
    assert store.exists(digest)


def test_grace_period_is_configurable(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(ORPHAN)
    _age(store, digest, hours=2)

    stats = sweep_blobs(store, is_referenced=lambda _: False, grace=timedelta(hours=1))

    assert stats.deleted == 1


def test_sweep_reports_what_it_scanned(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    kept = store.put(SHARED)
    dropped = store.put(ORPHAN)
    _age(store, kept, hours=48)
    _age(store, dropped, hours=48)

    stats = sweep_blobs(store, is_referenced=lambda sha: sha == kept)

    assert (stats.scanned, stats.deleted, stats.kept_referenced) == (2, 1, 1)


def test_sweep_ignores_staged_partial_writes(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(ORPHAN)
    partial = store.path_for(digest).with_name("leftover.tmp")
    partial.write_bytes(b"half")

    stats = sweep_blobs(store, is_referenced=lambda _: False)

    assert stats.scanned == 1
    assert partial.exists()


def test_sweep_predicate_can_be_a_reference_count(tmp_path: Path) -> None:
    """Mirrors the production wiring: referenced == count(*) > 0."""
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(SHARED)
    _age(store, digest, hours=48)
    counts = {digest: 2}

    stats = sweep_blobs(store, is_referenced=lambda sha: counts.get(sha, 0) > 0)

    assert stats.deleted == 0
