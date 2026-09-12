# SQLAlchemy models and Alembic migrations

Alembic migrations define the physical database schema. SQLAlchemy models are a
minimal, typed interface for constructing queries and transferring rows between
PostgreSQL and Python.

Keeping those responsibilities distinct avoids accidental schema changes,
implicit queries, and ORM behavior that is difficult to see in code. It is
particularly useful for applications with complex PostgreSQL schemas and
query-heavy data access.

## Alembic owns the physical schema

Treat the migration history as the authoritative definition of tables, columns,
constraints, indexes, functions, extensions, partitions, and database-owned
data.

Do not create application or test databases with
`Base.metadata.create_all()`. Build them by applying the real migration history.
This exercises the same schema that production uses and prevents tests from
silently accepting differences between SQLAlchemy metadata and Alembic.

SQLAlchemy metadata is intentionally incomplete. Leave Alembic's
`target_metadata` unset:

```python
target_metadata = None
```

Write every migration explicitly. Do not use Alembic autogeneration: the ORM
deliberately omits database details and therefore cannot describe the changes
required by the physical schema.

Do not edit a migration after it has been merged, shared with another
environment, or deployed. Add a new migration that moves every supported
database state forward.

An unreleased migration on a feature branch may be edited while the feature is
still being developed. If that migration has already been applied to a local or
test database, recreate the database and apply the migration history from
scratch. Alembic records revision identifiers, not migration file contents, so
it will not notice that an already-recorded revision has changed. Editing the
migration therefore implies reloading every disposable database that has seen
that revision.

## Keep SQLAlchemy models minimal

Model only what SQLAlchemy needs to read rows, write rows, and type-check the
application's queries. Avoid copying physical schema information into the ORM
unless SQLAlchemy itself requires it.

In particular, constraints, indexes, string lengths, server defaults, triggers,
and other database details belong in Alembic migrations. Repeating them in ORM
metadata creates two schema descriptions that can drift while suggesting that
the metadata is complete enough for schema generation.

Use SQLAlchemy's typed declarative API:

```python
import uuid

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import MappedAsDataclass
from sqlalchemy.orm import mapped_column


class Base(MappedAsDataclass, DeclarativeBase):
    pass


class Product(Base, kw_only=True):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
```

Prefer keyword-only constructors and explicit values over ORM defaults that hide
how an entity is initialized.

Keeping all mapped classes in one dedicated `entities.py` is reasonable even
when the file becomes large. The file remains a mechanical declaration of the
database mapping and keeps the complete mapping easy to find. There is no need
to split it into domain modules solely because of its size. Keep the declarative
base and shared SQL types in small separate modules.

## Keep joins explicit

The physical database should use foreign-key constraints wherever they protect
referential integrity. Those constraints belong in migrations. Do not repeat a
foreign key in the SQLAlchemy model merely because it exists in PostgreSQL.

Add ORM `ForeignKey` declarations only when mapper behavior requires them, such
as joined-table inheritance. Omitting the remaining declarations prevents
SQLAlchemy from inferring joins that should be visible in application code.

Because the mapper cannot infer every dependency between newly constructed
rows, make insertion order explicit when necessary. Flush a newly inserted
parent before adding a child that refers to it. Put delete cascades in the
database schema or execute the required deletes explicitly; do not depend on an
ORM relationship cascade.

Write both sides and the condition explicitly:

```python
statement = (
    sa.select(Order, Product)
    .select_from(Order)
    .join(Product, Product.order_id == Order.id)
)
```

Do not define ORM `relationship()` mappings. Access such as `order.products` is
intentionally unavailable. Relationships can hide queries, load unexpectedly
large object graphs, and trigger asynchronous lazy-loading failures. Fetch the
required data with an explicit statement instead.

Prefer SQLAlchemy's explicit `select`, `insert`, `update`, and `delete`
expressions over elaborate ORM navigation. Stay close enough to SQL that the
tables, joins, predicates, ordering, and locking behavior remain apparent from
the Python code.

## Build rich projections deliberately

Loading an object graph is not required to return a nested result. For complex
read models, consider PostgreSQL JSON and JSONB functions to construct the
projection inside the query.

The resulting JSON value is not statically typed. Validate it at the database
boundary with a Pydantic `TypeAdapter`:

```python
import uuid

import pydantic
import sqlalchemy as sa


class ProductSummary(pydantic.BaseModel):
    id: uuid.UUID
    name: str


product_summaries = pydantic.TypeAdapter(list[ProductSummary])

payload = sa.func.jsonb_build_object(
    "id",
    Product.id,
    "name",
    Product.name,
)

rows = await session.scalars(
    sa.select(payload).select_from(Product).order_by(Product.name, Product.id)
)
result = product_summaries.validate_python(rows.all())
```

This is especially useful for projections containing aggregates or several
nested collections. For ordinary single-table results, selecting mapped rows
and converting them explicitly is usually clearer.

Keep the projection and its Pydantic model next to each other or otherwise make
their connection obvious. A change to either side must fail validation rather
than silently producing a malformed API response.

### Return typed results from projection queries

For complex projections, let a query function own filtering, ordering,
pagination, execution, and DTO validation. Accept the session and explicit
filter arguments, and return DTOs or a typed search result. Keep SQLAlchemy rows
and unvalidated JSON inside that function. When returning a total count, apply
the same filters and calculate it before pagination.

With strict DTOs, select the JSONB projection as SQL text and use
`TypeAdapter.validate_json()`. JSON validation accepts JSON representations of
UUIDs and dates; strict Python-mode validation expects their Python instances.

Test these queries against PostgreSQL. Cover nested values, missing optional
joins, filters, and pagination totals. An absent joined object should produce
JSON null when the DTO expects `None`, rather than an object whose fields are
all null. These tests verify the SQL projection and its DTO contract; static
checking protects callers after validation.

## Make database types explicit

Use `Mapped[T]` for every mapped attribute and centralize repeated type mappings
in `Base.type_annotation_map`.

For `StrEnum` values, decide explicitly whether PostgreSQL stores the Python
member name or its string value. SQLAlchemy stores member names by default. When
the string value is the database representation, configure it deliberately:

```python
import enum
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import MappedAsDataclass


class ProductStatus(enum.StrEnum):
    AVAILABLE = "available"
    DISCONTINUED = "discontinued"


def enum_values[EnumT: enum.StrEnum](enum_type: type[EnumT]) -> list[str]:
    return [member.value for member in enum_type]


class Base(MappedAsDataclass, DeclarativeBase):
    type_annotation_map: ClassVar[dict[object, object]] = {
        ProductStatus: sa.Enum(
            ProductStatus,
            name="product_status",
            values_callable=enum_values,
        ),
    }
```

Name PostgreSQL enum types explicitly. Changing a Python enum must not
accidentally change which strings SQLAlchemy reads or writes.

For JSON objects, prefer `dict[str, object]` to `dict[str, Any]` where the code
does not genuinely require arbitrary unchecked Python values.

## Enforce aware datetimes and inject mutation timestamps

Define timestamp columns as `DateTime(timezone=True)` in Alembic migrations so
PostgreSQL uses `timestamp with time zone`:

```python
sa.Column(
    "created_at",
    sa.DateTime(timezone=True),
    nullable=False,
)
```

Use a shared SQLAlchemy type that checks values when they cross the ORM/database
boundary. It must reject a naive datetime both on the way into the database and
on the way out, regardless of where that value originated:

```python
import datetime
import typing

import sqlalchemy as sa
from sqlalchemy.orm import mapped_column


class NaiveDatetimeError(ValueError):
    pass


def require_aware(
    value: datetime.datetime | None,
) -> datetime.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise NaiveDatetimeError("Naive datetime is not allowed")
    return value


class AwareDateTime(sa.TypeDecorator[datetime.datetime]):
    impl = sa.DateTime(timezone=True)
    cache_ok = True

    @typing.override
    def process_bind_param(
        self,
        value: datetime.datetime | None,
        dialect: sa.Dialect,
    ) -> datetime.datetime | None:
        del dialect
        return require_aware(value)

    @typing.override
    def process_result_value(
        self,
        value: datetime.datetime | None,
        dialect: sa.Dialect,
    ) -> datetime.datetime | None:
        del dialect
        return require_aware(value)


AwareTimestamp = typing.Annotated[
    datetime.datetime,
    mapped_column(AwareDateTime(), nullable=False),
]
```

Mapped entities can then use the shared annotation:

```python
class Product(Base, kw_only=True):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    created_at: Mapped[AwareTimestamp]
    updated_at: Mapped[AwareTimestamp]
```

Python's type system does not distinguish naive and aware `datetime.datetime`
values. Once the application boundaries enforce awareness, intermediate code
should use `datetime.datetime` and assume the invariant. Do not scatter
defensive awareness checks throughout use cases.

Capture one aware timestamp at the operation boundary and pass it into the use
case. Use that value for every `created_at` and `updated_at` mutation in the
transaction:

```python
async def create_product(
    session: AsyncSession,
    *,
    product_id: uuid.UUID,
    name: str,
    at: datetime.datetime,
) -> Product:
    product = Product(
        id=product_id,
        name=name,
        created_at=at,
        updated_at=at,
    )
    session.add(product)
    return product
```

Do not use PostgreSQL `now()`, server timestamp defaults, ORM timestamp default
factories, or hidden update hooks for these fields. An injected value ensures
that every mutation belonging to one transaction observes the same time. It
also allows tests to move time forward explicitly; database-owned current time
makes that form of time travel difficult or impossible.

## Put durable invariants in PostgreSQL

Use database constraints for invariants that must hold across every writer,
including concurrent transactions and maintenance scripts. Complex schemas may
need check constraints, unique or partial indexes, exclusion constraints,
foreign keys, triggers, and custom functions.

Give constraints and indexes stable, explicit names. Application code may use a
constraint name to translate an expected integrity violation into a business
outcome:

```python
import psycopg


def is_duplicate_product(error: sa.exc.IntegrityError) -> bool:
    if not isinstance(error.orig, psycopg.errors.UniqueViolation):
        return False
    return error.orig.diag.constraint_name == "uq_products_name"
```

Match both the expected violation and the exact constraint. Reraise every
unrecognized integrity error; treating all constraint failures as the same
business outcome hides programming and schema errors.

## Make transaction ownership visible

Create a typed asynchronous session maker and put transaction ownership at an
application boundary:

```python
type Sessionmaker = async_sessionmaker[AsyncSession]


async with sessionmaker.begin() as session:
    await execute_use_case(session, ...)
```

Routes, jobs, or top-level use cases may own that boundary. Lower-level query and
service functions receive the existing session and must not commit or roll it
back independently. Use `flush()` when subsequent work needs generated values
or an integrity check before the transaction ends.

Passing a session through the complete operation also makes transaction scope,
locking, and read-after-write behavior explicit.

Success commits; exceptions, including `RequestRejected`, roll back. When a
use case returns an error value, its entrypoint must raise the mapped exception
before leaving the transaction boundary. Returning an HTTP error response
normally would instead commit pending writes.

If a failed-attempt counter must survive rejection, persist it in an explicitly
separate transaction and session. A savepoint does not survive rollback of its
outer transaction. Keep this exceptional persistence separate from the rejected
operation's writes; do not add a commit option to an HTTP exception.

## Package and run migrations reliably

Store the Alembic environment and revision files inside an installable Python
package. Resolve the script directory with `importlib.resources` so migrations
remain available from wheels and do not depend on the current working directory
or repository layout.

Construct the Alembic configuration programmatically from the database URL and
packaged script location. Escape values passed through Alembic's configuration
parser, including percent characters that may occur in credentials.

Run production migrations through one safe entry point that:

1. resolves the target revisions;
2. reads the current database revisions;
3. returns immediately when they already match;
4. acquires a PostgreSQL advisory lock scoped to the database;
5. reads the current revisions again after acquiring the lock;
6. applies the migrations;
7. verifies that the database reached the target revisions;
8. records useful timing and failure information;
9. releases the lock reliably.

Keep the unlocked Alembic invocation private. It remains useful for creating a
fresh isolated test template, but production callers should not be able to
accidentally bypass migration serialization.

Never run migrations as part of application startup. Migration is an explicit
operational action, invoked through a dedicated command or infrastructure job.
Run that action at the intended point in the deployment process, separately
from starting the application.

Use `heads` when the migration runner supports multiple intentional branches,
and compare complete sets of revisions rather than assuming that
`alembic_version` contains exactly one row. Projects that require a linear
history should additionally fail continuous integration when more than one head
exists.

## Write migrations for real data

A migration must work against the data and schema that are already deployed,
not just against an empty database. Separate complicated migration work into
clearly named steps inside the revision:

- introduce structures that can coexist with the old model;
- backfill and transform existing data;
- add or validate new constraints;
- remove obsolete structures only when they are no longer needed.

Seed rows that are part of a schema invariant belong in the migration and should
be tested. Environment-specific or optional development data does not.

Do not write Alembic downgrades. Make the policy explicit in every revision:

```python
def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported")
```

Development databases are disposable and can be recreated from the migration
history. Production problems should normally be corrected with a forward
migration or, when necessary, by restoring a verified backup. A structural
downgrade cannot generally reconstruct data discarded or transformed by the
upgrade, so maintaining one creates work and a potentially false sense of
safety.

Take and verify backups according to the deployment's risk before applying
material migrations.

## Test the migration boundary

Create the database-test template by applying the complete Alembic history to an
empty PostgreSQL database. Clone that migrated template for isolated tests. This
keeps tests fast while ensuring that ORM queries run against the real schema.

Check that applying the complete history reaches the expected Alembic heads.
For revisions that transform existing data, test the upgrade from the immediate
predecessor with representative data. Add focused checks for the data,
constraints, indexes, or seed rows the revision changes.

Test concurrent migration attempts in the migration runner's tests when it owns
locking; this does not need a separate test for every revision.

Run strict type checking and formatting over the Alembic environment and
revision scripts as well as the application. Migration code executes in
production and should not be excluded merely because some revisions began as
generated output.
