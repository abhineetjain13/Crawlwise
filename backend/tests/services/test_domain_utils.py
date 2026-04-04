from app.services.domain_utils import normalize_domain


def test_normalize_domain_strips_standard_port_without_scheme():
    assert normalize_domain("example.com:443/path") == "example.com"
    assert normalize_domain("example.com:80/path") == "example.com"
