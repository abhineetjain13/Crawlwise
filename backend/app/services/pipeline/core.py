# PHASE-3 FACADE: implementation moved to app.services.pipeline.extraction_loop.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.pipeline import extraction_loop as _extraction_loop

_sys.modules[__name__] = _extraction_loop
