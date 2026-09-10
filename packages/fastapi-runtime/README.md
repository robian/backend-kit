# fastapi-runtime

Typed, lifespan-scoped application contexts for FastAPI applications whose
route tree is expensive to construct.

Build the application and mount its routes once. A context factory supplies
fresh runtime dependencies each time the application lifespan starts. The same
context is available from the root application and nested FastAPI mounts.

```python
import contextlib
import dataclasses
import typing
from collections.abc import AsyncIterator

import fastapi
from fastapi_runtime import AppContextBinding
from fastapi_runtime import ContextFactory


@dataclasses.dataclass(frozen=True, slots=True)
class Context:
    catalog: object


context_binding = AppContextBinding(Context)
ContextDependency = typing.Annotated[Context, fastapi.Depends(context_binding)]


def create_app(context_factory: ContextFactory[Context]) -> fastapi.FastAPI:
    app = fastapi.FastAPI(lifespan=context_binding.lifespan(context_factory))
    app.mount("/api/v1", create_v1_app())
    return app


@contextlib.asynccontextmanager
async def create_context() -> AsyncIterator[Context]:
    yield Context(catalog=object())
```

Tests can keep that application session-scoped and select a fresh context
factory around each client lifespan:

```python
from fastapi.testclient import TestClient
from fastapi_runtime import ContextFactorySlot


context_slot = ContextFactorySlot[Context]()
app = create_app(context_slot)

with context_slot.use(create_test_context):
    with TestClient(app) as client:
        response = client.get("/api/v1/products")
```
