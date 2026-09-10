# backend-kit

Small, independent Python backend components. Each package can be installed
directly from its directory or from this repository using a Git subdirectory.

| Package | Purpose |
| --- | --- |
| [`fastapi-runtime`](packages/fastapi-runtime) | Fresh typed application contexts without rebuilding the FastAPI route tree. |
| [`pg-test-db`](packages/pg-test-db) | Fast PostgreSQL test databases cloned from an initialized template. |
| [`typed-result`](packages/typed-result) | A small, strictly typed `Result[T, E]` with exhaustive pattern matching. |

## Guidance

- [Structuring FastAPI application code](docs/application-structure.md)
- [OpenAPI contracts with FastAPI and Pydantic](docs/openapi-schema.md)
- [SQLAlchemy models and Alembic migrations](docs/sqlalchemy-alembic.md)
- [Testing FastAPI and SQLAlchemy applications](docs/testing.md)

Install a package from a pinned repository revision by selecting its
subdirectory:

```toml
[project]
dependencies = ["pg-test-db"]

[tool.uv.sources]
pg-test-db = { git = "https://github.com/robian/backend-kit.git", rev = "COMMIT_SHA", subdirectory = "packages/pg-test-db" }
```

## Development

Install every workspace package and its development tools:

```console
uv sync --all-packages
```

Run the checks:

```console
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest packages/fastapi-runtime/tests packages/pg-test-db/tests \
  packages/typed-result/tests \
  --db-url postgresql+psycopg://postgres:postgres@localhost:5432/
uv build --all-packages
```
