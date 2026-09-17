"""Provider registry."""

from __future__ import annotations

from ..config import Settings
from .base import BaseProvider, ProviderError
from .cpapi import CpApiProvider
from .demo import DemoProvider
from .flex import FlexProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    DemoProvider.name: DemoProvider,
    FlexProvider.name: FlexProvider,
    CpApiProvider.name: CpApiProvider,
}


def get_provider(settings: Settings, name: str | None = None) -> BaseProvider:
    key = (name or settings.provider or "demo").strip().lower()
    provider_cls = PROVIDERS.get(key)
    if provider_cls is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ProviderError(f"Unknown provider {key!r}. Choose one of: {known}.")
    return provider_cls(settings)


def describe_providers(settings: Settings) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for key, provider_cls in PROVIDERS.items():
        provider = provider_cls(settings)
        # Only probe the network for the provider that is actually selected.
        if key == settings.provider and key != "demo":
            ok, detail = provider.check()
        elif key == "demo":
            ok, detail = True, "always available"
        else:
            ok, detail = True, "not selected"
        out.append(
            {
                "name": key,
                "label": provider_cls.label,
                "selected": key == settings.provider,
                "ready": ok,
                "detail": detail,
            }
        )
    return out


__all__ = [
    "BaseProvider",
    "ProviderError",
    "PROVIDERS",
    "get_provider",
    "describe_providers",
]
