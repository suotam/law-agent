"""Tests for the content-addressed filesystem blob store."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from law_agent.storage import FilesystemBlobStore

CONTRACT = b"Smluvni strany se dohodly."


def test_put_returns_the_sha256_of_the_content(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    assert store.put(CONTRACT) == hashlib.sha256(CONTRACT).hexdigest()


def test_round_trip_returns_the_exact_bytes(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    digest = store.put(CONTRACT)

    with store.open(digest) as handle:
        assert handle.read() == CONTRACT


def test_the_same_content_is_stored_once(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    first = store.put(CONTRACT)
    second = store.put(CONTRACT)

    assert first == second
    assert len(list(store.iter_blobs())) == 1


def test_put_touches_an_existing_blob(tmp_path: Path) -> None:
    """The GC sweep spares young blobs; a deduplicated put has to keep it young."""
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(CONTRACT)
    target = store.path_for(digest)
    stale = target.stat().st_mtime - 10_000
    os.utime(target, (stale, stale))

    store.put(CONTRACT)

    assert target.stat().st_mtime > stale


def test_path_is_sharded_by_the_first_four_hex_characters(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    digest = store.put(CONTRACT)

    assert store.path_for(digest) == tmp_path / digest[:2] / digest[2:4] / digest


def test_exists_and_delete(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(CONTRACT)

    assert store.exists(digest)
    assert store.delete(digest) is True
    assert not store.exists(digest)
    assert store.delete(digest) is False


def test_open_raises_for_a_missing_blob(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.open("0" * 64)


def test_iter_blobs_ignores_partial_writes(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    digest = store.put(CONTRACT)
    partial = store.path_for(digest).with_name("leftover.tmp")
    partial.write_bytes(b"half")

    assert [path.name for path in store.iter_blobs()] == [digest]
