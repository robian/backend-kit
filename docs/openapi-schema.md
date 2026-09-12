# OpenAPI contracts with FastAPI and Pydantic

The generated OpenAPI document is the contract between the backend and its
consumers. It should describe what the backend accepts and emits on the wire,
not merely what is convenient to express inside Python.

This matters when clients, operation definitions, or runtime validators are
generated from OpenAPI. An inaccurate schema can still produce valid-looking
generated code, but that code will provide guarantees about the wrong
contract.

## API models describe the wire format

Treat Pydantic models used at the API boundary as data transfer objects. Their
types, required fields, defaults, and discriminators should describe serialized
requests and responses precisely.

Python-side convenience belongs outside those models when it would weaken the
wire contract. For example, use a factory function to supply repeated constants
instead of making a response field optional through a default.

### Keep domain types out of the API contract

Derive OpenAPI from dedicated API DTOs. Do not reuse domain models, enums, or
unions directly as DTO field types. Otherwise, adding a value to a domain enum
or union can silently expand the public API.

Convert domain values to their API representation explicitly and exhaustively:

```python
import enum
import typing

import pydantic


class ProductState(enum.StrEnum):
    AVAILABLE = "available"
    ARCHIVED = "archived"
    INTERNAL = "internal"


class ProductResponse(pydantic.BaseModel):
    state: typing.Literal["available", "archived"]


def product_state_response(
    state: ProductState,
) -> typing.Literal["available", "archived"]:
    match state:
        case ProductState.AVAILABLE:
            return "available"
        case ProductState.ARCHIVED:
            return "archived"
        case ProductState.INTERNAL:
            raise ValueError("Internal products cannot be exposed")

    typing.assert_never(state)
```

When a domain variant is added, type checking should fail at the exhaustive
conversion. Resolving that failure requires an explicit decision: extend the
DTO and intentionally change the API, or handle the new value without exposing
it, for example by rejecting or filtering it.

This keeps API stability independent from changes to the database and domain
model. Pydantic's `from_attributes` remains useful, but it does not replace this
boundary. Use it only when the DTO still owns every exposed enum and union, or
when an explicit conversion handles differences between the domain and API
value sets.

### Required response fields

Do not give a response field a default when clients may rely on that field being
present. This is especially important for discriminators such as `type`, `kind`,
`status`, `code`, and `availability`.

```python
import typing

import pydantic


class ProductNotFoundResponse(pydantic.BaseModel):
    code: typing.Literal["product_not_found"]
    product_id: str
```

Defining `code` as follows would make it optional in the generated schema, even
if the application happens to serialize it every time:

```python
code: typing.Literal["product_not_found"] = "product_not_found"
```

If repeating the constant is inconvenient, keep the response model truthful and
provide a factory function:

```python
def product_not_found_response(product_id: str) -> ProductNotFoundResponse:
    return ProductNotFoundResponse(
        code="product_not_found",
        product_id=product_id,
    )
```

Defaults remain appropriate when omission is genuinely part of the API
contract. This is common for request fields, but less common for fields in a
response that the frontend uses for narrowing or rendering.

### Omitted and nullable values

An optional query parameter commonly uses `None` inside Python to mean that the
parameter was omitted. That does not necessarily mean that `null` is a valid
wire value.

Use `SkipJsonSchema[None]` to retain the Python sentinel without advertising
`null` in OpenAPI:

```python
import typing

import fastapi
from pydantic.json_schema import SkipJsonSchema


ProductKind = typing.Literal["physical", "digital"]


async def search_products(
    kind: typing.Annotated[
        ProductKind | SkipJsonSchema[None],
        fastapi.Query(),
    ] = None,
) -> None: ...
```

The resulting parameter is optional, but a transmitted value is limited to
`"physical"` or `"digital"`. Generated enum types therefore do not acquire an
artificial `null` member.

Use the three forms deliberately:

| Meaning | Annotation |
| --- | --- |
| Required value | `T` with no default |
| May be omitted, but not transmitted as `null` | `T | SkipJsonSchema[None] = None` |
| May be omitted or explicitly transmitted as `null` | `T | None = None` |

`SkipJsonSchema` changes schema generation, not runtime validation. Use it only
when `None` is an internal representation of omission. Do not use it to hide a
`null` value that a JSON request can accept or a response can emit.

### Numeric values and units

Prefer integers in explicit units for quantities with a defined precision.
For example, represent durations as `duration_ms = 4500` rather than fractional
seconds, and energy as `energy_wh = 1250` rather than fractional kWh. Include the
unit in field names and describe it in the schema so consumers do not have to
infer the scale.

Choose units fine enough to preserve the required resolution. Use smaller units
when whole milliseconds or Wh are insufficient. Define whether values between
representable units are rejected or rounded, and specify the rounding rule.
Convert vendor and display units at boundaries without passing exact values
through binary floats.

This avoids binary fractional rounding and the need to choose a JSON
representation for decimal values. Keep integer ranges within the exact limits
supported by consumers; JavaScript numbers, for example, cannot represent every
integer beyond `2**53 - 1` in magnitude. Division and unit conversion may still
require explicit rounding.

Use `Decimal` when decimal arithmetic is required, with an explicit serialized
representation and rounding policy. Use `float` when approximate numerical
computation is intentional. A tolerance-based comparison changes the meaning
of equality; it does not repair a numeric type that cannot meet the contract.

### Require timezone-aware datetimes

Use Pydantic's `AwareDatetime` for API fields that represent an instant. This
rejects a datetime without a UTC offset when validating a request or response
DTO:

```python
import pydantic


class ScheduleRequest(pydantic.BaseModel):
    starts_at: pydantic.AwareDatetime
```

Python's type system does not distinguish naive and aware `datetime.datetime`
values. Enforce awareness when data enters through a Pydantic DTO, then let
intermediate application code use `datetime.datetime` and rely on that
invariant instead of repeatedly checking `tzinfo`.

## Route-owned responses

JSON handlers return their success DTO and raise for unsuccessful outcomes.
Omit `response_model` so FastAPI derives the success schema from the handler's
return annotation. Set `status_code` at registration when success is not 200.
Do not override it by mutating an injected `Response`. File streams and
no-content responses retain their appropriate response types.

Represent route-specific rejections with a route-owned error DTO. Raise a shared
`RequestRejected(error_dto)` exception and have one async exception handler
serialize that DTO as the body of a 400 response. The exception accepts neither
a status-code override nor a commit flag. Use the generic exceptions for other
failure categories. Error codes and exhaustive mappings from use-case errors
remain owned by the route; mapping functions return exceptions, and the handler
raises them.

This keeps handlers callable as ordinary Python functions: callers receive a
success DTO or catch an exception, without unpacking a `JSONResponse`.

Declare the 400 error DTO and applicable generic error schemas in `responses`
at route registration. This metadata documents OpenAPI; it does not dispatch,
validate, or select runtime responses. Keep those declarations visible rather
than accumulating them through nested routers.

## Stable operation identifiers

An OpenAPI operation identifier is part of the client-facing contract. Generated
operation definitions and client APIs commonly use it as their stable name.

Do not rely on FastAPI's default operation identifiers. They combine the handler
name, normalized route path, and HTTP method, producing identifiers that are
noisy and coupled to details that do not represent the operation's identity.

Give every route an explicit, globally unique semantic `name` and configure
FastAPI to use that name as its operation identifier:

```python
import fastapi


def generate_operation_id(route: fastapi.routing.APIRoute) -> str:
    return route.name


app = fastapi.FastAPI(
    generate_unique_id_function=generate_operation_id,
)

router = fastapi.APIRouter()
router.add_api_route(
    "/products",
    search_products,
    methods=["GET"],
    name="search_products",
)
```

Treat the route name as public API. Moving the handler, renaming its Python
function, or changing its module should not alter the operation identifier.
Rename it only as an intentional client-facing contract change.

Do not derive operation identifiers from Python module paths. Although this
produces cleaner output than FastAPI's default, reorganizing backend source code
would then unnecessarily rename generated client operations.

Generate the OpenAPI schema during tests or startup and fail on duplicate
operation identifiers. FastAPI reports duplicates as warnings by default; do
not allow those warnings to pass unnoticed.

## Framework-owned responses

Some responses originate outside the route handler. Authentication dependencies,
shared dependencies, routing, infrastructure code, and global exception handlers
can all terminate a request.

Convert these cross-cutting failures into stable response DTOs with centralized
exception handlers. At route registration, explicitly indicate which categories
apply to that route—for example, whether it participates in authentication or
has a shared not-found outcome.

Python cannot statically determine every exception that may escape from a route
and its dependency tree. Consequently, these declarations do not provide the
same guarantee as an exhaustively converted business result. A route's metadata
can drift from its dependency configuration.

That limited risk is intentional. Eliminating it would require wrapping FastAPI's
route and dependency execution in a separate contract framework. For most
applications, explicit declarations and focused tests provide a better trade-off.

## Guarantee boundary

The intended guarantees are:

| Area | Guarantee |
| --- | --- |
| Successful route result | Strongly typed response model |
| Route-specific unsuccessful result | Typed and exhaustively converted by the route |
| Generic framework failure | Centralized response model and exception handler |
| Applicability of a generic failure to one route | Explicit declaration, maintained by the application |
| Absence of every possible undeclared exception | Not statically guaranteed |

The frontend should treat every response declared in OpenAPI as part of the
operation. Adding a status or adding a member to a response discriminator should
therefore change the generated TypeScript types and expose non-exhaustive caller
code during type checking.

## Verification

Use tests and generation checks where they provide meaningful evidence:

- Test each centralized exception handler's status and serialized response
  shape.
- Inspect representative routes in the generated OpenAPI document to verify
  that applicable generic responses are present.
- Generate frontend types, operation definitions, and runtime schemas from the
  same OpenAPI document.
- Fail continuous integration when generated frontend artifacts are stale.
- Type-check frontend callers exhaustively against status and discriminator
  unions.

Do not try to prove with per-route tests that an exception can never occur.
Tests can demonstrate configured behavior, but they cannot establish the
absence of every failure from the complete dependency and middleware stack.
