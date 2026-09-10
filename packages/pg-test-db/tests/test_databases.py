from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL

from pg_test_db import create_template_db


def test_template_clones_are_isolated_and_cleaned_up(server_db_url: str) -> None:
    template_name: str
    first_clone_name: str
    shorthand_url = server_db_url.replace("postgresql+psycopg", "postgresql", 1)

    with create_template_db(
        shorthand_url,
        initialize=_create_schema,
        prefix="package_test_template_",
    ) as template:
        template_name = template.name
        assert _database_exists(server_db_url, template_name)

        with template.clone(prefix="package_test_clone_") as first_clone:
            first_clone_name = first_clone.name
            assert first_clone.template_name == template.name
            assert _row_count(first_clone.url) == 1
            _insert_row(first_clone.url)
            assert _row_count(first_clone.url) == 2

        assert not _database_exists(server_db_url, first_clone_name)

        with template.clone(prefix="package_test_clone_") as second_clone:
            assert _row_count(second_clone.url) == 1

    assert not _database_exists(server_db_url, template_name)


def test_clone_is_cleaned_up_when_consumer_fails(server_db_url: str) -> None:
    clone_name: str | None = None

    with create_template_db(
        sa.make_url(server_db_url),
        initialize=_create_schema,
    ) as template:
        with pytest.raises(ExpectedError):
            with template.clone() as clone:
                clone_name = clone.name
                raise ExpectedError

        assert clone_name is not None
        assert not _database_exists(server_db_url, clone_name)


def test_cleanup_tolerates_an_already_removed_clone(server_db_url: str) -> None:
    with create_template_db(server_db_url, initialize=_create_schema) as template:
        with template.clone() as clone:
            _drop_database(server_db_url, clone.name)


def test_template_is_cleaned_up_when_migration_fails(server_db_url: str) -> None:
    template_name = f"package_test_failure_{uuid.uuid4().hex[:12]}"

    def fail_initialization(database_url: URL) -> None:
        assert database_url.database == template_name
        raise ExpectedError

    with pytest.raises(ExpectedError):
        with create_template_db(
            server_db_url,
            initialize=fail_initialization,
            name=template_name,
        ):
            pytest.fail("migration failure should prevent the context from opening")

    assert not _database_exists(server_db_url, template_name)


@pytest.mark.parametrize(
    "server_db_url",
    [
        "sqlite://",
        "postgresql+asyncpg://postgres@example.test/",
        "postgresql+psycopg://postgres@example.test/application",
    ],
)
def test_invalid_server_urls_are_rejected(server_db_url: str) -> None:
    with pytest.raises(ValueError):
        with create_template_db(server_db_url, initialize=lambda _: None):
            pytest.fail("invalid URL should prevent the context from opening")


def test_invalid_database_names_are_rejected(server_db_url: str) -> None:
    with pytest.raises(ValueError, match="invalid database name"):
        with create_template_db(
            server_db_url,
            initialize=lambda _: None,
            name="invalid-name",
        ):
            pytest.fail("invalid name should prevent the context from opening")


class ExpectedError(Exception):
    pass


def _create_schema(database_url: URL) -> None:
    engine = sa.create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    CREATE TABLE products (
                        id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        name text NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                sa.text("INSERT INTO products (name) VALUES ('Desk lamp')")
            )
    finally:
        engine.dispose()


def _row_count(database_url: URL) -> int:
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            return connection.execute(
                sa.text("SELECT count(*) FROM products")
            ).scalar_one()
    finally:
        engine.dispose()


def _insert_row(database_url: URL) -> None:
    engine = sa.create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("INSERT INTO products (name) VALUES ('Coffee grinder')")
            )
    finally:
        engine.dispose()


def _database_exists(server_db_url: str, database_name: str) -> bool:
    server_url = sa.make_url(server_db_url)
    if server_url.drivername == "postgresql":
        server_url = server_url.set(drivername="postgresql+psycopg")
    engine = sa.create_engine(
        server_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as connection:
            result = connection.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            )
            return result.scalar_one_or_none() is not None
    finally:
        engine.dispose()


def _drop_database(server_db_url: str, database_name: str) -> None:
    server_url = sa.make_url(server_db_url)
    if server_url.drivername == "postgresql":
        server_url = server_url.set(drivername="postgresql+psycopg")
    engine = sa.create_engine(
        server_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text(f"DROP DATABASE {database_name}"))
    finally:
        engine.dispose()
