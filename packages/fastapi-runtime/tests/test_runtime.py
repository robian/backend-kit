import asyncio
import contextlib
import dataclasses
import typing
from collections.abc import AsyncGenerator

import fastapi
import httpx2
import pytest

from fastapi_runtime import AppContextBinding
from fastapi_runtime import ContextFactory
from fastapi_runtime import ContextFactorySlot


@dataclasses.dataclass(frozen=True, slots=True)
class CatalogContext:
    catalog_name: str


def _context_factory(name: str) -> ContextFactory[CatalogContext]:
    @contextlib.asynccontextmanager
    async def create_context() -> AsyncGenerator[CatalogContext]:
        yield CatalogContext(catalog_name=name)

    return create_context


def _create_app(
    binding: AppContextBinding[CatalogContext],
    context_factory: ContextFactory[CatalogContext],
) -> tuple[fastapi.FastAPI, fastapi.FastAPI, fastapi.FastAPI]:
    context_dependency = typing.Annotated[
        CatalogContext,
        fastapi.Depends(binding.resolve),
    ]

    root = fastapi.FastAPI(lifespan=binding.lifespan(context_factory))
    api = fastapi.FastAPI()
    nested = fastapi.FastAPI()

    @root.get("/context")
    async def get_root_context(context: context_dependency) -> dict[str, str]:
        return {"catalog_name": context.catalog_name}

    @api.get("/context")
    async def get_mounted_context(context: context_dependency) -> dict[str, str]:
        return {"catalog_name": context.catalog_name}

    api.mount("/nested", nested)
    root.mount("/api", api)
    root.mount("/duplicate", api)
    return root, api, nested


def test_reuses_application_tree_with_fresh_contexts() -> None:
    binding = AppContextBinding(CatalogContext)
    slot = ContextFactorySlot[CatalogContext]()
    app, mounted_app, nested_app = _create_app(binding, slot)
    route_ids = tuple(id(route) for route in app.routes)

    async def run_lifespan(name: str) -> None:
        with slot.use(_context_factory(name)):
            async with app.router.lifespan_context(app):
                transport = httpx2.ASGITransport(app=app)
                async with httpx2.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as client:
                    for path in ("/context", "/api/context", "/duplicate/context"):
                        response = await client.get(path)
                        assert response.status_code == 200
                        assert response.json() == {"catalog_name": name}

        for current in (app, mounted_app, nested_app):
            assert not hasattr(current.state, "_fastapi_runtime_context")

    asyncio.run(run_lifespan("first"))
    asyncio.run(run_lifespan("second"))

    assert tuple(id(route) for route in app.routes) == route_ids


def test_context_dependency_fails_outside_lifespan() -> None:
    binding = AppContextBinding(CatalogContext)
    app = fastapi.FastAPI()
    request = fastapi.Request({"type": "http", "app": app})

    with pytest.raises(RuntimeError, match="CatalogContext"):
        binding.resolve(request)


def test_context_factory_must_yield_expected_type() -> None:
    binding = AppContextBinding(CatalogContext)

    @contextlib.asynccontextmanager
    async def wrong_factory() -> AsyncGenerator[object]:
        yield object()

    factory = typing.cast(ContextFactory[CatalogContext], wrong_factory)
    app = fastapi.FastAPI(lifespan=binding.lifespan(factory))

    async def start_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(TypeError, match="object, expected CatalogContext"):
        asyncio.run(start_lifespan())


def test_rejects_overlapping_application_lifespans() -> None:
    binding = AppContextBinding(CatalogContext)
    app, _, _ = _create_app(binding, _context_factory("catalog"))

    async def overlap_lifespans() -> None:
        async with app.router.lifespan_context(app):
            async with app.router.lifespan_context(app):
                pass

    with pytest.raises(
        RuntimeError,
        match="already installed",
    ):
        asyncio.run(overlap_lifespans())


def test_cleanup_does_not_remove_a_replaced_context() -> None:
    binding = AppContextBinding(CatalogContext)
    app, mounted_app, _ = _create_app(binding, _context_factory("catalog"))
    replacement = CatalogContext(catalog_name="replacement")

    async def replace_context() -> None:
        async with app.router.lifespan_context(app):
            mounted_app.state._fastapi_runtime_context = replacement

    asyncio.run(replace_context())

    assert mounted_app.state._fastapi_runtime_context is replacement
    del mounted_app.state._fastapi_runtime_context


def test_slot_requires_a_selected_factory() -> None:
    slot = ContextFactorySlot[CatalogContext]()

    with pytest.raises(RuntimeError, match="no context factory"):
        slot()


def test_slot_rejects_overlapping_selection_and_recovers() -> None:
    slot = ContextFactorySlot[CatalogContext]()
    first = _context_factory("first")
    second = _context_factory("second")

    with slot.use(first):
        with pytest.raises(
            RuntimeError,
            match="already selected",
        ):
            with slot.use(second):
                pass

    with slot.use(second):
        assert slot() is not None
