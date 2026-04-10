from __future__ import annotations

from app.services.extract.source_parsers import _infer_embedded_blob_family


def test_infer_embedded_blob_family_uses_original_key_case_for_payload_lookup() -> None:
    payload = {
        "Product": {
            "name": "Widget",
            "price": "19.99",
            "sku": "SKU-1",
        }
    }

    assert _infer_embedded_blob_family(payload) == "product_json"
