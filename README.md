# postgres-test-databases

Small, typed PostgreSQL lifecycle primitives for test suites that need both a
fast shared database and selectively isolated databases.

The package creates and migrates one PostgreSQL template, seals it against
connections, and creates inexpensive clones from it. Every public operation is
context-managed so databases are removed when a test fails.

```python
from collections.abc import Iterator

import pytest
from postgres_test_databases import Database
from postgres_test_databases import TemplateDatabase
from postgres_test_databases import create_template_db


@pytest.fixture(scope="session")
def template_database(server_db_url: str) -> Iterator[TemplateDatabase]:
    with create_template_db(
        server_db_url,
        initialize=upgrade_schema,
    ) as template:
        yield template


@pytest.fixture(scope="session")
def shared_database(
    template_database: TemplateDatabase,
) -> Iterator[Database]:
    with template_database.clone(prefix="myapp_shared_") as database:
        yield database


@pytest.fixture
def isolated_database(
    template_database: TemplateDatabase,
) -> Iterator[Database]:
    with template_database.clone(prefix="myapp_isolated_") as database:
        yield database
```

The migration callback receives a `sqlalchemy.URL` for the newly created
template database. A server URL must not include a database name:

```python
import sqlalchemy


def upgrade_schema(database_url: sqlalchemy.URL) -> None:
    alembic.command.upgrade(make_alembic_config(database_url), "head")
```

The PostgreSQL role must be able to create and drop databases, mark a database
as a template, and terminate connections to databases it owns.
