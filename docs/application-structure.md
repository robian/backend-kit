# Structuring FastAPI application code

A versioned route handler is the boundary of an API operation. It owns the
operation's HTTP contract and coordinates the application behavior needed to
implement that contract. Behavior shared by multiple operations or entrypoints
belongs in application services.

## Route handlers own versioned API operations

Define route handlers as plain async Python functions with explicit arguments.
FastAPI resolves those arguments during an HTTP request, while tests and other
Python callers can invoke the same function by supplying them directly.

A route handler may coordinate:

- request DTOs and path or query parameters;
- authentication and authorization dependencies;
- SQLAlchemy sessions and queries;
- database mutations;
- application services and external integrations;
- audit recording;
- conversion to response DTOs and HTTP errors.

Keep that coordination in the handler while it belongs to only that API
operation. Extract behavior when another operation or entrypoint needs to share
it.

Read handlers may construct their SQLAlchemy statements directly. When a query
or projection becomes large, move it into a specifically named module within
the same route package, such as `_queries.py`. It remains part of that versioned
API operation rather than becoming shared application behavior prematurely.

## Share behavior through application services

When multiple handlers, jobs, commands, or other entrypoints need the same
transport-independent behavior, extract it into an application service.

Organize services by the capability they provide:

```text
src/example/
  application/
    services/
      audit.py
      email.py
      role_assignments.py
      user_profiles.py
```

Prefer concrete module and function names over generic classes such as
`ProductService`. A service can be a function, a small collection of related
functions, a protocol representing an external capability, or a stateful
object when state is genuinely required.

Application-service interfaces use application and domain values. Pass
database sessions, operation timestamps, authorization context, and external
capabilities explicitly. Return typed domain values or typed expected outcomes.
The calling entrypoint converts those values into its own public contract.

This keeps application services independent from FastAPI request and response
objects and from version-specific DTOs. The dependency direction remains from
the API toward application services, models, and integrations.

## Share code, not route handlers

Route handlers should not call other route handlers. A handler includes the
contract and coordination choices of one specific API operation. Calling it
from another handler couples both operations through request DTOs, response
DTOs, dependency annotations, error conversion, and future contract changes.

When two handlers need the same behavior, extract that behavior into a shared
function first. Each handler then calls the shared function and independently
maps its result to its own response contract.

Shared code that remains specific to one API version can stay within that
version's API package. Examples include response rendering, common DTO
conversion, and query fragments shared by related endpoints. Only
transport-independent behavior belongs in application services.

## Let API versions remain independent

Each API version owns its route handlers, request DTOs, response DTOs, error
mapping, and orchestration. A new version can therefore change an operation
without changing the implementation retained for an older contract.

Build a new version around its actual requirements. Reuse existing application
services where their behavior already matches both versions. When two concrete
versions reveal additional stable behavior, extract that behavior at that
point and let both handlers depend on it.

This keeps compatibility decisions at the versioned API boundary. Shared
application code represents behavior demonstrated to be stable instead of a
prediction about what a future API will need.

## Keep other entrypoints explicit

Jobs, command-line commands, migration utilities, and bootstrap operations are
entrypoints in their own right. Give each one a small function that accepts its
dependencies explicitly and calls the application services it needs.

An operation shared in full by several entrypoints can itself become a named
application service. Bootstrap behavior for establishing initial application
state is a typical example: it originates outside ordinary HTTP operation flow
and benefits from one explicitly callable implementation.
