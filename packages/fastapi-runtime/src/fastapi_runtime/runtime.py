from __future__ import annotations

import contextlib
import typing
from collections.abc import AsyncGenerator
from collections.abc import Generator
from collections.abc import Iterator

import fastapi
from starlette.routing import Mount

type ContextFactory[ContextT] = typing.Callable[
    [],
    contextlib.AbstractAsyncContextManager[ContextT],
]
type Lifespan = typing.Callable[
    [fastapi.FastAPI],
    contextlib.AbstractAsyncContextManager[None],
]

_STATE_ATTRIBUTE = "_fastapi_runtime_context"
_MISSING = object()


class AppContextBinding[ContextT]:
    """Bind one typed context to a FastAPI application lifespan."""

    def __init__(self, context_type: type[ContextT]) -> None:
        self._context_type = context_type

    def __call__(self, request: fastapi.Request) -> ContextT:
        context = getattr(request.app.state, _STATE_ATTRIBUTE, _MISSING)
        if not isinstance(context, self._context_type):
            raise RuntimeError(
                f"{self._context_type.__name__} is not available in app state"
            )
        return context

    def lifespan(self, context_factory: ContextFactory[ContextT]) -> Lifespan:
        """Create a FastAPI lifespan that installs contexts from the factory."""

        @contextlib.asynccontextmanager
        async def lifespan(app: fastapi.FastAPI) -> AsyncGenerator[None]:
            async with context_factory() as context:
                if not isinstance(context, self._context_type):
                    raise TypeError(
                        "context factory yielded "
                        f"{type(context).__name__}, expected "
                        f"{self._context_type.__name__}"
                    )

                apps = tuple(_iter_fastapi_apps(app))
                if any(
                    getattr(current.state, _STATE_ATTRIBUTE, _MISSING) is not _MISSING
                    for current in apps
                ):
                    raise RuntimeError("application context is already installed")

                for current in apps:
                    setattr(current.state, _STATE_ATTRIBUTE, context)

                try:
                    yield
                finally:
                    for current in reversed(apps):
                        if (
                            getattr(current.state, _STATE_ATTRIBUTE, _MISSING)
                            is context
                        ):
                            delattr(current.state, _STATE_ATTRIBUTE)

        return lifespan


class ContextFactorySlot[ContextT]:
    """Temporarily select the context factory used by a reusable application."""

    def __init__(self) -> None:
        self._factory: ContextFactory[ContextT] | None = None

    def __call__(self) -> contextlib.AbstractAsyncContextManager[ContextT]:
        factory = self._factory
        if factory is None:
            raise RuntimeError("no context factory is selected")
        return factory()

    @contextlib.contextmanager
    def use(self, factory: ContextFactory[ContextT]) -> Generator[None]:
        """Select a factory for the duration of one application lifespan."""
        if self._factory is not None:
            raise RuntimeError("a context factory is already selected")

        self._factory = factory
        try:
            yield
        finally:
            self._factory = None


def _iter_fastapi_apps(app: fastapi.FastAPI) -> Iterator[fastapi.FastAPI]:
    pending = [app]
    seen: set[int] = set()

    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        yield current

        pending.extend(
            route.app
            for route in reversed(current.routes)
            if isinstance(route, Mount) and isinstance(route.app, fastapi.FastAPI)
        )
