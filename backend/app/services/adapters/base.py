# Base adapter interface for platform-specific extraction.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AdapterResult:
    """Structured data returned by a platform adapter."""

    records: list[dict] = field(default_factory=list)
    source_type: str = "adapter"
    confidence: float = 0.95
    adapter_name: str = ""


class BaseAdapter(ABC):
    """All platform adapters implement this interface.

    Adapters are called during the DISCOVER stage and return structured
    records extracted from platform-specific API endpoints or embedded
    data structures.  They are separate from the generic DOM/selector
    extraction pipeline.
    """

    name: str = "base"

    # Domains this adapter handles.  Checked by the registry.
    domains: list[str] = []

    @abstractmethod
    async def can_handle(self, url: str, html: str) -> bool:
        """Return True if this adapter should run for the given URL/HTML."""
        ...

    @abstractmethod
    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract structured records from the page.

        ``surface`` is the user-declared surface type so the adapter can
        tailor its output (e.g. listing vs detail fields).
        """
        ...
