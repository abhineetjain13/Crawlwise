"""Shared adapter record types."""
from __future__ import annotations

from typing import TypeAlias

AdapterRecord: TypeAlias = dict[str, object]
AdapterRecords: TypeAlias = list[AdapterRecord]
