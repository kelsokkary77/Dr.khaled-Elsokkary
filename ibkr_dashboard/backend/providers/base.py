"""Provider contract shared by every IBKR data source."""

from __future__ import annotations

import abc

from ..config import Settings
from ..models import PortfolioSnapshot


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a snapshot.

    The message is shown verbatim in the dashboard's error banner, so it should
    read as an instruction to the user, not a stack trace.
    """


class BaseProvider(abc.ABC):
    #: Stable identifier used in config (``IBKR_PROVIDER``) and stored snapshots.
    name: str = "base"
    #: One-line description surfaced by ``GET /api/providers``.
    label: str = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abc.abstractmethod
    def fetch(self) -> PortfolioSnapshot:
        """Pull everything this source can offer and normalize it."""

    def check(self) -> tuple[bool, str]:
        """Cheap readiness probe: is this provider configured and reachable?"""
        return True, "ready"
