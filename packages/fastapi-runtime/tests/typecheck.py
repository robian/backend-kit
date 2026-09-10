import typing

import fastapi

from fastapi_runtime import AppContextBinding
from fastapi_runtime import ContextFactory
from fastapi_runtime import ContextFactorySlot


class CatalogContext:
    pass


binding = AppContextBinding(CatalogContext)
slot = ContextFactorySlot[CatalogContext]()
factory: ContextFactory[CatalogContext] = slot
lifespan = binding.lifespan(factory)
ContextDependency = typing.Annotated[
    CatalogContext,
    fastapi.Depends(binding.resolve),
]

typing.assert_type(binding, AppContextBinding[CatalogContext])
typing.assert_type(slot, ContextFactorySlot[CatalogContext])
typing.assert_type(factory, ContextFactory[CatalogContext])
typing.assert_type(lifespan, typing.Callable)
