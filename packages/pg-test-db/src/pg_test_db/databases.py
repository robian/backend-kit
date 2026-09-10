from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from collections.abc import Generator
from contextlib import AbstractContextManager
from contextlib import contextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine

type Initializer = Callable[[URL], None]
type Url = str | URL

_DATABASE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DEFAULT_MAINTENANCE_DATABASE = "postgres"
_DEFAULT_TEMPLATE_PREFIX = "test_template_"
_DEFAULT_CLONE_PREFIX = "test_database_"


@dataclass(frozen=True, kw_only=True, slots=True)
class Database:
    """A temporary database cloned from a migrated template."""

    server_url: URL
    maintenance_database: str
    template_name: str
    name: str
    url: URL


@dataclass(frozen=True, kw_only=True, slots=True)
class TemplateDatabase:
    """A migrated PostgreSQL database used as a clone source."""

    server_url: URL
    maintenance_database: str
    name: str
    url: URL

    def clone(
        self,
        *,
        name: str | None = None,
        prefix: str = _DEFAULT_CLONE_PREFIX,
    ) -> AbstractContextManager[Database]:
        """Create a temporary clone and drop it on context exit."""
        return _cloned_database(self, name=name, prefix=prefix)


@contextmanager
def create_template_db(
    server_db_url: Url,
    *,
    initialize: Initializer,
    name: str | None = None,
    prefix: str = _DEFAULT_TEMPLATE_PREFIX,
    maintenance_database: str = _DEFAULT_MAINTENANCE_DATABASE,
) -> Generator[TemplateDatabase]:
    """Create, initialize, and safely dispose of a PostgreSQL template database."""
    server_url = _parse_server_url(server_db_url)
    _validate_database_name(maintenance_database)
    template_name = name or _make_database_name(prefix)
    _validate_database_name(template_name)
    template = TemplateDatabase(
        server_url=server_url,
        maintenance_database=maintenance_database,
        name=template_name,
        url=_database_url(server_url, template_name),
    )

    _create_database(
        server_url,
        maintenance_database=maintenance_database,
        name=template.name,
        template="template0",
    )
    try:
        initialize(template.url)
        _seal_template(template)
        yield template
    finally:
        _drop_database(
            server_url,
            maintenance_database=maintenance_database,
            name=template.name,
            is_template=True,
        )


@contextmanager
def _cloned_database(
    template: TemplateDatabase,
    *,
    name: str | None,
    prefix: str,
) -> Generator[Database]:
    database_name = name or _make_database_name(prefix)
    _validate_database_name(database_name)
    database = Database(
        server_url=template.server_url,
        maintenance_database=template.maintenance_database,
        template_name=template.name,
        name=database_name,
        url=_database_url(template.server_url, database_name),
    )

    _create_database(
        template.server_url,
        maintenance_database=template.maintenance_database,
        name=database.name,
        template=template.name,
    )
    try:
        yield database
    finally:
        _drop_database(
            template.server_url,
            maintenance_database=template.maintenance_database,
            name=database.name,
            is_template=False,
        )


def _parse_server_url(value: Url) -> URL:
    url = sa.make_url(value) if isinstance(value, str) else value
    if not url.drivername.startswith("postgresql"):
        raise ValueError("server_db_url must use PostgreSQL")
    if url.database not in (None, ""):
        raise ValueError("server_db_url must not include a database name")
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("server_db_url must use the psycopg driver")
    return url


def _database_url(server_url: URL, database_name: str) -> URL:
    _validate_database_name(database_name)
    return server_url.set(database=database_name)


def _make_database_name(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _validate_database_name(database_name: str) -> None:
    if _DATABASE_NAME_PATTERN.fullmatch(database_name) is None:
        raise ValueError(f"invalid database name: {database_name!r}")


def _create_database(
    server_url: URL,
    *,
    maintenance_database: str,
    name: str,
    template: str,
) -> None:
    _validate_database_name(name)
    _validate_database_name(template)
    engine = _create_admin_engine(server_url, maintenance_database)
    try:
        with engine.connect() as connection:
            quoted_name = _quote_identifier(connection, name)
            quoted_template = _quote_identifier(connection, template)
            connection.execute(
                sa.text(f"CREATE DATABASE {quoted_name} TEMPLATE {quoted_template}")
            )
    finally:
        engine.dispose()


def _seal_template(template: TemplateDatabase) -> None:
    engine = _create_admin_engine(
        template.server_url,
        template.maintenance_database,
    )
    try:
        with engine.connect() as connection:
            quoted_name = _quote_identifier(connection, template.name)
            connection.execute(
                sa.text(f"ALTER DATABASE {quoted_name} WITH ALLOW_CONNECTIONS false")
            )
            connection.execute(
                sa.text(f"ALTER DATABASE {quoted_name} WITH IS_TEMPLATE true")
            )
    finally:
        engine.dispose()


def _drop_database(
    server_url: URL,
    *,
    maintenance_database: str,
    name: str,
    is_template: bool,
) -> None:
    _validate_database_name(name)
    engine = _create_admin_engine(server_url, maintenance_database)
    try:
        with engine.connect() as connection:
            if not _database_exists(connection, name):
                return

            quoted_name = _quote_identifier(connection, name)
            if is_template:
                connection.execute(
                    sa.text(f"ALTER DATABASE {quoted_name} WITH ALLOW_CONNECTIONS true")
                )
                connection.execute(
                    sa.text(f"ALTER DATABASE {quoted_name} WITH IS_TEMPLATE false")
                )
            _terminate_database_connections(connection, name)
            connection.execute(sa.text(f"DROP DATABASE {quoted_name}"))
    finally:
        engine.dispose()


def _create_admin_engine(server_url: URL, maintenance_database: str) -> Engine:
    return sa.create_engine(
        _database_url(server_url, maintenance_database),
        isolation_level="AUTOCOMMIT",
    )


def _quote_identifier(connection: Connection, value: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(value)


def _database_exists(connection: Connection, database_name: str) -> bool:
    result = connection.execute(
        sa.text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
        {"database_name": database_name},
    )
    return result.scalar_one_or_none() is not None


def _terminate_database_connections(
    connection: Connection,
    database_name: str,
) -> None:
    connection.execute(
        sa.text(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = :database_name
              AND pid <> pg_backend_pid()
            """
        ),
        {"database_name": database_name},
    )
