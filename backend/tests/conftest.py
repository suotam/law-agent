"""Shared fixtures and a builder for synthetic fragment lists."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import count
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from law_agent.config import settings
from law_agent.ingestion.laws import Fragment, LawDocument

REPO_ROOT = Path(__file__).resolve().parent.parent

LAWS_DIR = REPO_ROOT / "data" / "laws"

TEST_DATABASE = "law_agent_test"

REAL_LAWS = [
    LAWS_DIR / "zakon_o_svobodnem_pristupu_k_informacim.json",
    LAWS_DIR / "zakonik_prace.json",
]


class FragmentBuilder:
    """Builds fragment lists the way the API emits them: flat, depth-ordered.

    Keeps tests readable -- a test declares structure, not bookkeeping::

        builder.add("Paragraf", 3, designation="§ 1", content="§ 1")
        builder.add("Odstavec_Dc", 4, designation="(1)", content="(1) Text.")
    """

    def __init__(self, eli: str = "/eli/cz/sb/2020/1/2024-01-01") -> None:
        self.eli = eli
        self._ids = count(1)
        self._positions = count(0)
        self._path: list[str] = []
        self.fragments: list[Fragment] = []

    def add(
        self,
        type_name: str,
        depth: int,
        *,
        segment: str | None = None,
        designation: str | None = None,
        heading: str | None = None,
        content: str | None = None,
        is_repealed: bool = False,
        path: str | None = None,
    ) -> Fragment:
        """Add one fragment.

        ``depth`` drives nesting, exactly as in the API. ``path`` overrides the
        derived ``fragment_id`` tail, which is needed to reproduce the real
        data's quirk where a wrapper's id is not a prefix of what it wraps.
        """
        del self._path[depth:]
        segment = segment or f"frag_{next(self._ids)}"
        self._path.append(segment)
        fragment = Fragment(
            id=next(self._ids),
            fragment_id=f"{self.eli}/" + (path or "/".join(self._path)),
            position=next(self._positions),
            type=type_name,
            depth=depth,
            designation=designation,
            heading=heading,
            content=content,
            is_repealed=is_repealed,
        )
        self.fragments.append(fragment)
        return fragment

    def document(self, **kwargs: bool) -> LawDocument:
        return LawDocument.from_fragments(self.fragments, **kwargs)


@pytest.fixture
def builder() -> FragmentBuilder:
    b = FragmentBuilder()
    b.add("Virtual_Document", 0, segment="dokument")
    b.add("Virtual_Prefix", 1, segment="prefix")
    b.add("Prefix_Number", 2, content="1")
    b.add("Prefix_Type", 2, content="ZÁKON")
    b.add("Prefix_Title", 2, content="o testování")
    b.add("Virtual_Norma", 1, segment="norma")
    return b


@pytest.fixture(params=REAL_LAWS, ids=lambda p: p.stem)
def real_document(request: pytest.FixtureRequest) -> LawDocument:
    path: Path = request.param
    if not path.exists():
        pytest.skip(f"sample law {path.name} not present")
    return LawDocument.from_json(path)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """A throwaway ``law_agent_test`` database with the schema migrated onto it.

    Skips instead of failing when compose is not up, the same way missing law
    samples skip ``real_document``. No testcontainers (compose already runs the
    real thing, and the project has no CI) and no SQLite -- that would test a
    database without jsonb, without partial indexes and with different
    transaction semantics from the one this runs on.
    """
    admin_url = make_url(settings.database_url).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        connection = admin.connect()
    except OperationalError:
        admin.dispose()
        pytest.skip("Postgres is not running (docker compose up -d postgres)")

    with connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    admin.dispose()

    test_url = make_url(settings.database_url).set(database=TEST_DATABASE)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", test_url.render_as_string(hide_password=False))
    command.upgrade(config, "head")

    engine = create_engine(test_url)
    yield engine
    engine.dispose()

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """A session inside an outer transaction that is rolled back afterwards.

    ``join_transaction_mode="create_savepoint"`` is what keeps that working when
    the code under test commits: a repository's ``commit()`` releases a
    savepoint instead of ending the outer transaction.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()
