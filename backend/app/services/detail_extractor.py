# PHASE-3 FACADE: implementation moved to app.services.extract.detail_materializer.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.extract import detail_materializer as _detail_materializer

_sys.modules[__name__] = _detail_materializer
