# Python tooling

## Ruff

Use Ruff for formatting and linting, installed as a project development dependency:

```console
uv add --dev ruff
```

Commit `uv.lock` and run tools through `uv run` to use the project's versions.

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "ASYNC", "RUF"]
extend-select = ["ANN", "PYI"]
preview = true

[tool.ruff.lint.isort]
force-single-line = true

[tool.ruff.format]
docstring-code-format = true
```

Set `tool.ruff.target-version` to the minimum supported Python version and
`tool.ruff.src` to the project's source roots.

`ANN` enforces function annotations; `PYI` adds typing-related checks.
These additions and lint preview follow
[Astral's recommended configuration](https://docs.astral.sh/ty/coming-from-mypy-or-pyright/#recommended-configuration).
Preview affects all selected lint families, including `RUF`, and does not enable
preview formatting when set under `tool.ruff.lint`. Review new findings when
upgrading Ruff.

Run both checks locally and in CI:

```console
uv run ruff format --check .
uv run ruff check .
```

Linting does not check formatter compliance. Apply formatting with
`uv run ruff format .`.

## Suppressions

Fix valid findings. For intentional code, suppress the specific finding locally
and explain the reason when it is not obvious:

```python
# Keep this handler on FastAPI's event loop.
async def read_health() -> HealthResponse:  # ruff: ignore[unused-async]
    return HealthResponse()
```

Use named-rule suppressions with a Ruff version that supports this syntax. Keep
unused-suppression checking enabled so exceptions can be removed when no longer
needed. Do not introduce callable classes or artificial awaits just to avoid a
warning.

See [application structure](application-structure.md) for async handlers,
dependencies, exception handlers, and route composition, and
[numeric values and units](openapi-schema.md#numeric-values-and-units) for numeric
representation choices. Assess each finding against that behavior before
suppressing it; framework exceptions do not justify disabling the rule globally.

To inspect a single rule, including suppressed findings:

```console
uv run ruff check . --select RUF029 --preview --ignore-noqa
```

## Type checkers

Use Basedpyright, ty, and Pyrefly. Their different inference and diagnostic rules
expose different gaps. The validated versions are Basedpyright 1.40.1,
ty 0.0.80, and Pyrefly 1.3.0. Most findings were resolved with clearer code;
use narrow suppressions for library or checker limitations. A diagnostic is not
necessarily a runtime bug.

### Why Basedpyright

Basedpyright replaces standalone Pyright. It retains Pyright's core checking and
adds diagnostics that exposed lost type information in DTO construction,
SQLAlchemy row access, and test helpers. Its import-cycle checks also helped
identify package initializers that unnecessarily imported application code.

Running both adds substantial overlap. They also interpret the same `# pyright:`
comments: Pyright can reject a suppression for a Basedpyright-only rule as
unnecessary. Use `[tool.basedpyright]` and install only Basedpyright; keep ty and
Pyrefly for complementary checking.

Prefer explicit DTO constructor arguments over `**model.model_dump()` and typed
test helpers over arbitrary keyword dictionaries. For SQLAlchemy rows, explicit
unpacking preserves individual column types. Complex JSONB projections should
be validated into DTOs at the database boundary and exercised against PostgreSQL;
see [rich projections](sqlalchemy-alembic.md#build-rich-projections-deliberately).

See the [testing guidance](testing.md#keep-tests-explicit-and-focused) for choosing
useful assertions and keeping test helpers typed.

### Validated checker settings

Set Python versions and source roots to match the project. Keep `reportAny`
enabled: it reports uses of dynamically typed values. `reportExplicitAny`, which
remains enabled by the default preset, separately reports explicit `Any`
annotations. Review warnings as well as errors.

Disable `reportUnusedCallResult`: builders and database operations are often
called for their side effects. Disable `reportUnannotatedClassAttribute` to retain
attribute inference, while enabling `reportIncompatibleUnannotatedOverride` to
check incompatible subclass overrides.

```toml
[tool.basedpyright]
pythonVersion = "3.14"
venvPath = "."
venv = ".venv"
include = ["src", "tests", "alembic"]
strict = ["src/*", "tests/*", "alembic/*"]
reportImplicitOverride = true
reportUnnecessaryTypeIgnoreComment = true
reportUnknownMemberType = true
reportUnknownVariableType = true
reportUnknownArgumentType = true
reportUnknownLambdaType = true
reportUnknownParameterType = true
reportUnusedCallResult = false
reportAny = "warning"
reportUnannotatedClassAttribute = false
reportIncompatibleUnannotatedOverride = true
```

The ty settings follow its
[recommended configuration](https://docs.astral.sh/ty/coming-from-mypy-or-pyright/#recommended-configuration),
not `--error all`; the complementary Ruff annotation rules are described above.

```toml
[tool.ty.rules]
dynamic-function-decorator-return = "error"
missing-type-argument = "error"
possibly-unresolved-reference = "warn"
unsound-return-statement = "error"

[tool.pyrefly]
preset = "strict"
python-version = "3.14.0"
project-includes = ["src", "tests", "alembic"]

[tool.pyrefly.errors]
unknown-argument-type = "error"
unknown-attribute-type = "error"
unknown-variable-type = "error"
```

Keep Pyrefly's default inference behavior; no migration-oriented inference
overrides were needed. Run all three locally and in CI:

```console
uv run basedpyright
uv run ty check
uv run pyrefly check --min-severity warn
```

Pyrefly hides warnings by default, so an ordinary zero-error result does not mean
there are no remaining diagnostics. Basedpyright returns a nonzero exit status
for the warnings in this configuration.

### Workarounds for checker limitations

Keep workarounds local, explain their cause, and reassess them on upgrades.
These were needed with the validated versions; do not add them preemptively:

- **ty and Pydantic schema/dump methods:** return types can become `Unknown`
  through name resolution involving Pydantic's `dict` method. Affected returns
  use `# ty: ignore[unsound-return-statement] astral-sh/ty#1747`.
  See [ty #1747](https://github.com/astral-sh/ty/issues/1747).
- **ty and Clerk:** an SDK call can produce `Divergent` despite usable model
  annotations. The affected return has a local
  `ty: ignore[unsound-return-statement]` with that explanation. This was not
  established to have the same cause as Pyrefly's Clerk issue.
- **Basedpyright and SQLAlchemy's declarative base:** the documented
  `Base(MappedAsDataclass, DeclarativeBase)` pattern triggers the conservative
  multiple-inheritance rule. Use `# pyright: ignore[reportUnsafeMultipleInheritance]`
  on that class and explain that SQLAlchemy supports the combination.
- **Basedpyright and Structlog:** `WrappedLogger` aliases `Any`. A processor
  implementing that interface uses a local
  `# pyright: ignore[reportExplicitAny, reportAny]`. Restoring `get_config()` with
  `configure(**saved_config)` uses `# pyright: ignore[reportAny]`, because the
  library returns an untyped dictionary. Explain both exceptions locally.
- **Pyrefly and Clerk imports:** `from clerk_backend_api import models` loses
  types, including inside SDK return annotations. A local stub restored the
  types, but maintaining a checker-specific package override was not worthwhile.
  Use a scoped configuration override for the adapter and its tests instead:

```toml
# Temporary workaround for Pyrefly's Clerk import resolution.
# Also hides unrelated unknown arguments/variables in these files.
# Remove when the SDK imports resolve correctly; replace example with the package.
[[tool.pyrefly.sub-config]]
matches = "*/example/integrations/clerk/**"

[tool.pyrefly.sub-config.errors]
unknown-argument-type = "ignore"
unknown-variable-type = "ignore"
```

SQLAlchemy `type_coerce()` supplies expression type information;
it does not validate values or emit a SQL cast. A Python `typing.cast()` likewise
needs a justified invariant rather than being used simply to obtain a clean run.

When a library returns `Any`, treating the value as `object` with
`typing.cast(object, value)` discards dynamic typing without claiming a more
specific type. Validate or narrow it before use. JSON DTO dictionaries should
use `pydantic.JsonValue` where nested JSON is allowed, rather than `Any`.
