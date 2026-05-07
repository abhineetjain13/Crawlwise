# PHASE-3 FACADE: implementation moved to app.services.shared.field_coerce.
# Keep public imports stable until all callers are rewired.

from __future__ import annotations

import sys as _sys

from app.services.shared import field_coerce as _field_coerce

_sys.modules[__name__] = _field_coerce
