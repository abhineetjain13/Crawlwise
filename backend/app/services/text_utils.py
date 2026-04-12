from __future__ import annotations


def normalized_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()
