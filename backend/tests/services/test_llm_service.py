from app.services.llm_service import mask_key


def test_mask_key_handles_none():
    assert mask_key(None) == "Not configured"
