# Testing FastAPI and SQLAlchemy applications

Tests for a database-backed application need more than fixtures. They need
reusable ways to construct valid database state, assemble application contexts,
and replace external systems. Keep that support as ordinary, typed Python in
the application package and use pytest only to manage lifetimes.

## Keep test support in the application package

Put reusable support under the application's importable namespace:

```text
src/example/
  testing/
    api.py
    fakes.py
    builders/
      products.py
      stores.py
    recipes/
      stocked_store.py
tests/
  conftest.py
  ...
```

This avoids making `tests` an informal second Python package whose behavior
depends on the test runner's import paths. It also gives test support the same
linting, type checking, module boundaries, and editor support as the rest of the
application.

Production modules must not import from `example.testing`. The dependency is
one-way: test support may use application code, but application code must not
depend on test support.

Keep the testing package independent from pytest. It should contain regular
functions, dataclasses, context managers, protocols, fakes, and spies. Those
objects can be called directly by tests or exposed through thin fixtures.

## Let pytest manage lifetimes

Fixtures are appropriate for resources whose creation and cleanup are governed
by pytest scopes, such as:

- the PostgreSQL server URL;
- a migrated template database;
- shared and isolated database clones;
- sessionmakers and engine disposal;
- the FastAPI route tree;
- the slot through which a test supplies an application context.

Do not express business state as a deep graph of fixtures. Fixtures such as
`customer`, `active_customer`, `customer_order`, and
`authenticated_customer_order_client` hide important setup behind parameter
names and become difficult to combine.

Expose a small number of capabilities instead. A fixture can return a
sessionmaker, an API test runtime, or a builder object. The test then calls
ordinary functions to create the state it needs. The setup remains visible and
can use normal arguments, control flow, and static types.

Keep `conftest.py` thin. If a fixture contains substantial application setup,
move that setup into a function or class in the application's testing package
and let the fixture only select its lifetime and dependencies.

## Test against PostgreSQL and the real schema

Any test that exercises persistence must use PostgreSQL. Do not replace it with
SQLite, an in-memory database, mocked SQLAlchemy sessions, mocked query chains,
or fake ORM entities. PostgreSQL types, constraints, locking, transactions,
JSONB expressions, indexes, and query semantics are part of the behavior being
tested.

Create test databases by applying the real Alembic migrations. Do not use
`Base.metadata.create_all()`: the SQLAlchemy metadata is intentionally not a
complete schema description.

Create one migrated template database for the test session and clone it for
the databases used by tests. Prefer two explicit modes:

- a session-scoped shared database for tests that create uniquely identified
  records and do not require an empty database;
- a per-test isolated clone for tests whose correctness depends on database-wide
  state, destructive operations, schema changes, or the absence of earlier
  records.

Shared-database tests should not delete their records afterward. Generate
collision-resistant identifiers and assert against the records created by the
test. Cleanup code adds time and can make tests interfere with one another.

Pure functions that do not access persistence need no database. The rule is
that PostgreSQL and SQLAlchemy behavior must never be simulated when database
behavior is part of the test.

## Use record builders for persisted state

A record builder creates one mapped record, or one tightly coupled set of rows
required by an inheritance mapping. Prefer a plain async function with explicit
arguments:

```python
import datetime
import uuid

from example import db
from example.model import Product


async def create_product(
    session: db.Session,
    *,
    store_id: uuid.UUID,
    product_id: uuid.UUID | None = None,
    name: str | None = None,
    created_at: datetime.datetime | None = None,
    updated_at: datetime.datetime | None = None,
) -> Product:
    product_id = product_id or uuid.uuid4()
    created_at = created_at or datetime.datetime.now(datetime.UTC)
    product = Product(
        id=product_id,
        store_id=store_id,
        name=name if name is not None else f"Test product {product_id.hex[:12]}",
        created_at=created_at,
        updated_at=updated_at or created_at,
    )
    session.add(product)
    await session.flush()
    return product
```

A record builder should:

- accept the caller's session;
- provide valid, collision-resistant defaults;
- allow relevant fields and identifiers to be overridden;
- add and flush records without committing;
- return typed mapped entities;
- make required links to existing records explicit.

The caller owns the transaction. A builder must not create a session or open
and commit its own transaction. This allows several builders to compose into
one atomic setup and lets a test deliberately exercise rollback behavior.

Record builders normally write mapped entities directly. Their purpose is to
establish a test precondition, not to test the application's creation workflow
while setting up another test. If state must be reached through a production
workflow, invoke that workflow explicitly so the dependency is visible in the
test.

Avoid one builder class containing methods for the entire schema. Organize
small builders by cohesive sets of records and expose them through a convenient
testing namespace where useful.

## Compose object graphs with recipes

When many tests need the same coherent object graph, compose record builders in
a targeted recipe. Use one caller-owned session and one timestamp for the
entire graph. Return a typed dataclass so tests can address the resulting
records without knowing how they were connected:

```python
import dataclasses
import datetime

from example import db
from example.model import Product
from example.model import Store
from example.testing import builders


@dataclasses.dataclass(frozen=True, slots=True)
class StockedStore:
    store: Store
    product: Product


async def create_stocked_store(
    session: db.Session,
    *,
    at: datetime.datetime | None = None,
) -> StockedStore:
    at = at or datetime.datetime.now(datetime.UTC)
    store = await builders.create_store(session, created_at=at)
    product = await builders.create_product(
        session,
        store_id=store.id,
        created_at=at,
    )
    return StockedStore(store=store, product=product)
```

A recipe may accept existing entities or identifiers when a test needs to join
new state to records it already created. Validate incompatible combinations and
fail clearly.

Prefer several focused recipes over a universal graph builder with dozens of
flags. A recipe should represent a recognizable state needed by tests, not an
alternative domain model or a second implementation of application behavior.

## Validate API responses with DTOs

Validate response bodies using the endpoint's response DTO before asserting
field values. Prefer `ResponseDTO.model_validate_json(response.content)` over
accessing untyped dictionaries from `response.json()`. Apply this to success and
error responses where a DTO exists. Keep explicit assertions for expected values
and behavior.

## Keep tests explicit and focused

Prefer direct calls over selecting known functions with `getattr` and passing
untyped argument dictionaries. Prefer typed recording fakes over inspecting
arbitrary values in mock call records. Remove redundant conversions when the
other checkers and runtime tests confirm they are unnecessary.

Review the value of a test before repairing its typing. Tests that merely repeat
DTO fields, enum values, descriptions, route registrations, or Pydantic-generated
OpenAPI fragments add maintenance without exercising application behavior.
Prefer HTTP tests of actual outcomes, DTO validation, and persistence assertions.
Type checkers can expose awkward test machinery; they cannot decide whether a
test is worth keeping.

See [Python tooling](python-tooling.md#type-checkers) for validated checker
settings and workarounds.

## Reuse the FastAPI route tree

Constructing and mounting a large FastAPI route tree can be considerably more
expensive than creating a fresh request context. Build the application shape
once at session scope and supply the context used by each test separately.

An application-owned test runtime can group:

- the shared FastAPI application;
- the context factory slot;
- the context factory for this test;
- the test database sessionmaker;
- authentication configuration and external-service fakes;
- a context manager that creates the HTTP test client.

This keeps dependency replacement explicit and avoids rebuilding the route tree
or mutating global dependency overrides for every test. An isolated and a
shared runtime can use the same application while differing only in their
sessionmaker and context factory.

Commit setup data before issuing an HTTP request when the request uses a
separate database session. For direct service or use-case tests, open the
transaction in the test and pass that session to both builders and the code
under test.

## Replace external systems at explicit boundaries

Tests may use application-owned fakes for external identity providers, mail
delivery, object storage, payment providers, and other remote systems. Construct
those fakes as part of the test context and inject them through the same
interfaces used by production adapters.

Prefer small fakes with explicit behavior. A dependency that should not be used
by a test can raise `AssertionError` when called. This fails closer to the
unexpected interaction than a loosely configured mock returning another mock.

For an interface with several methods, a shared test-support base can implement
each method by raising `NotImplementedError`. A focused fake inherits it and
overrides only the operations the test expects. Inherit the production interface
and keep explicit signatures and `@override` declarations. A recording fake can
collect typed observations such as `batch_sizes: list[int]`, allowing ordinary
assertions without extracting unknown values from mock call records.

Use monkeypatching only for unavoidable process-global or third-party state.
Do not patch application internals when an explicit dependency can represent
the same boundary more clearly.

## Preserve interface checks when using mocks

When a mock is useful, prefer `mock.create_autospec(Interface, instance=True)`.
It checks method call signatures at runtime; `mock.Mock(spec=Interface)` only
restricts attribute access. Autospec does not validate argument or return-value
types. Mock typing deliberately permits substitution for other types, so a
typechecker accepting a mock does not prove that it implements the interface.

If callers inspect calls or configure return values, annotate the helper with
the mock type so those controls remain available. For an interface whose
instances are not callable, autospec returns a `NonCallableMagicMock`. Use its
`NonCallableMock` base and an assertion to narrow the factory's `Any` return:

```python
from unittest import mock

from example.integrations.mail import MailClient


def mail_client_mock() -> mock.NonCallableMock:
    client = mock.create_autospec(MailClient, instance=True)
    assert isinstance(client, mock.NonCallableMock)
    return client
```

## Keep test-support code proportionate

Test-support code is maintained code, but it does not need a parallel test suite
that duplicates every feature test. Simple record builders are naturally
exercised wherever they are used. Add focused tests for recipes, fakes, or
runtime helpers when they contain branching, enforce invariants, or have
non-obvious lifecycle behavior.
