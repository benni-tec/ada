"""Composition root: binds every port to its implementation. Entrypoints get services from
the container built here and never import services or adapters themselves.

The bindings live in ada.composition.providers, one module per group of ports. Each module
exposes `provider`; every one of them is loaded.
"""

from dishka import AsyncContainer, Provider, make_async_container

from ada.composition import providers
from ada.config import Settings
from ada.discovery import modules


def create_container(settings: Settings, *extra: Provider) -> AsyncContainer:
    """Container shared by every entrypoint; each adds its framework provider. Providers
    passed here override the discovered ones, which tests use to swap in fakes."""
    discovered = [module.provider for module in modules(providers)]
    return make_async_container(*discovered, *extra, context={Settings: settings})
