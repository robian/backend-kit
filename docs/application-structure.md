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

## Put route composition in a router module

Build route maps explicitly with `build_router()` and
`router.add_api_route(...)`, keeping handler definitions separate from
registration so applications can compose routes with ordinary Python code.

For new resource packages, put `build_router()` in `router.py` alongside handler
modules such as `create.py`, `get.py`, and `search.py`. Leave `__init__.py` empty
and import the router module explicitly from the parent composition module.
This gives route registration a named home and keeps its imports out of package
initialization when callers only need a handler or DTO.

Existing packages can retain a builder in `__init__.py` with a targeted lint
exception when a structural change is not otherwise warranted. Defining the
builder does not construct routes at import time; calling it does.

## Keep nonblocking handlers and dependency factories async

Use `async def` for nonblocking route handlers, dependency factories, and
exception handlers, even when their bodies contain no `await`. FastAPI and
Starlette await async functions on the event loop and dispatch synchronous
functions to worker threads. Returning a response, retrieving an object from an
application context, or mapping an exception to an error response does not
warrant that thread-pool hop. This also applies to exception handlers registered
explicitly through `app.add_exception_handler(...)`.

Use awaitable APIs for I/O or explicitly offload blocking work from the event
loop. Ordinary helpers called directly by application code do not use FastAPI's
dispatch machinery and can remain synchronous. See
[FastAPI's execution model](https://fastapi.tiangolo.com/async/#very-technical-details).

If a linter flags an intentional async handler or dependency with a synchronous
body, use its supported syntax to suppress that finding locally. Keep the rule
enabled elsewhere; do not remove `async` or add an artificial await just to
satisfy the linter.

## Keep dependency factories and aliases together

Keep dependency factories and their `Annotated` aliases in one `dependency.py`
module. Define each alias immediately after its factory, with dependencies
ordered before the factories that consume them. Avoid separate `types.py` and
`factories.py` modules that must import each other.

Use a `Dependency` suffix for injected parameter aliases, such as
`SessionDependency = Annotated[db.Session, Depends(get_session)]`. Keep factory
return annotations and application-service parameters expressed in the actual
application type, such as `db.Session`. The alias describes FastAPI injection;
it does not introduce a different session type.

Keep this module together until there is a concrete reason to split it. Import
it directly rather than re-exporting its contents through `__init__.py`.

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
