# PHASE-3 FACADE: implementation moved to app.services.js_state.state_normalizer.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.js_state import state_normalizer as _state_normalizer

_sys.modules[__name__] = _state_normalizer
