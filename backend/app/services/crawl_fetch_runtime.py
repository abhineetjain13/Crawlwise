# PHASE-3 FACADE: implementation moved to app.services.fetch.fetch_context.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.fetch import fetch_context as _fetch_context

_sys.modules[__name__] = _fetch_context
