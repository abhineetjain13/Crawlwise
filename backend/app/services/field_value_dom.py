# PHASE-3 FACADE: implementation moved to app.services.dom.selector_engine.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.dom import selector_engine as _selector_engine

_sys.modules[__name__] = _selector_engine
