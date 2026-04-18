from __future__ import annotations

import json

from app.services.normalizers import normalize_review_value as _normalize_review_value


def review_bucket_fingerprint(value: object) -> str:
    """Generate a stable fingerprint for review-bucket deduplication."""
    normalized_value = _normalize_review_value(value)
    try:
        return json.dumps(normalized_value, sort_keys=True, default=str)
    except TypeError:
        return str(normalized_value)
