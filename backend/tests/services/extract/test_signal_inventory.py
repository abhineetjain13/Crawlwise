"""Property-based tests for signal inventory module.

Feature: extraction-pipeline-improvements
"""

from __future__ import annotations

from app.services.extract.signal_inventory import (
    build_signal_inventory,
    classify_page_type,
)
from hypothesis import given, settings
from hypothesis import strategies as st


def _make_inventory(
    *,
    json_ld=None,
    datalayer=None,
    next_data=None,
    hydrated_states=None,
    card_count: int = 0,
    has_price: bool = False,
    has_description: bool = False,
    has_specs: bool = False,
    is_listing_url: bool = False,
    is_detail_url: bool = False,
    link_count: int = 10,
    text_ratio: float = 0.5,
    domain: str = "example.com",
    surface: str = "",
) -> dict:
    return {
        "structured_data": {
            "json_ld": [] if json_ld is None else json_ld,
            "datalayer": {} if datalayer is None else datalayer,
            "next_data": next_data,
            "hydrated_states": [] if hydrated_states is None else hydrated_states,
        },
        "dom_patterns": {
            "card_count": card_count,
            "detail_markers": {
                "has_price": has_price,
                "has_description": has_description,
                "has_specs": has_specs,
            },
            "url_patterns": {
                "is_listing_url": is_listing_url,
                "is_detail_url": is_detail_url,
            },
        },
        "metadata": {
            "link_count": link_count,
            "text_ratio": text_ratio,
            "domain": domain,
            "surface": surface,
        },
    }


def _assert_inventory_is_populated(inventory: dict) -> None:
    assert inventory.get("structured_data") is not None
    assert inventory.get("dom_patterns") is not None
    assert inventory.get("metadata") is not None


# Property 1: Signal Inventory Completeness
@given(
    html=st.text(min_size=0, max_size=10000),
    url=st.one_of(
        st.just("https://example.com"),
        st.just("http://test.com/page"),
        st.builds(
            lambda domain, path: f"https://{domain}.com/{path}",
            domain=st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Nd"))),
            path=st.text(min_size=0, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Nd"))),
        ),
    ),
    surface=st.text(min_size=0, max_size=50),
)
@settings(max_examples=100, deadline=None)
def test_signal_inventory_completeness(html: str, url: str, surface: str):
    """Feature: extraction-pipeline-improvements, Property 1: Signal Inventory Completeness.

    For any valid HTML input, build_signal_inventory() SHALL produce an inventory mapping
    with non-null structured_data, dom_patterns, and metadata fields, even if those
    fields contain empty collections.

    Validates: Requirements 1.1, 1.2, 1.3
    """
    inventory = build_signal_inventory(html, url, surface)

    assert isinstance(inventory, dict)

    # Verify structured_data is non-null and is a dict
    _assert_inventory_is_populated(inventory)
    assert isinstance(inventory["structured_data"], dict)
    assert inventory["dom_patterns"] is not None
    assert isinstance(inventory["dom_patterns"], dict)
    assert isinstance(inventory["metadata"], dict)


# Property 2: Page Classification Validity
@given(
    structured_data=st.fixed_dictionaries(
        {
            "json_ld": st.lists(st.dictionaries(st.text(), st.text()), max_size=5),
            "datalayer": st.dictionaries(st.text(), st.text(), max_size=10),
            "next_data": st.one_of(st.none(), st.dictionaries(st.text(), st.text())),
            "hydrated_states": st.lists(st.dictionaries(st.text(), st.text()), max_size=3),
        }
    ),
    dom_patterns=st.fixed_dictionaries(
        {
            "card_count": st.integers(min_value=0, max_value=100),
            "detail_markers": st.fixed_dictionaries(
                {
                    "has_price": st.booleans(),
                    "has_description": st.booleans(),
                    "has_specs": st.booleans(),
                }
            ),
            "url_patterns": st.fixed_dictionaries(
                {
                    "is_listing_url": st.booleans(),
                    "is_detail_url": st.booleans(),
                }
            ),
        }
    ),
    metadata=st.fixed_dictionaries(
        {
            "link_count": st.integers(min_value=0, max_value=1000),
            "text_ratio": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            "domain": st.text(min_size=5, max_size=50),
            "surface": st.text(min_size=0, max_size=50),
        }
    ),
)
@settings(max_examples=100, deadline=None)
def test_page_classification_validity(
    structured_data: dict,
    dom_patterns: dict,
    metadata: dict,
):
    """Feature: extraction-pipeline-improvements, Property 2: Page Classification Validity.

    For any inventory mapping, classify_page_type() SHALL return exactly one of
    the values: "listing", "detail", or "unknown".

    Validates: Requirements 1.4, 1.5
    """
    inventory = {
        "structured_data": structured_data,
        "dom_patterns": dom_patterns,
        "metadata": metadata,
    }

    page_type = classify_page_type(inventory)

    # Verify page_type is one of the valid values
    assert page_type in {"listing", "detail", "unknown"}
    assert isinstance(page_type, str)


# Example-based tests for specific scenarios
def test_signal_inventory_with_empty_html():
    """Test signal inventory with empty HTML."""
    inventory = build_signal_inventory("", "https://example.com", "")

    _assert_inventory_is_populated(inventory)


def test_signal_inventory_with_valid_html():
    """Test signal inventory with valid HTML containing signals."""
    html = """
    <html>
        <head>
            <script type="application/ld+json">
                {"@type": "Product", "name": "Test Product"}
            </script>
        </head>
        <body>
            <div class="product-card">Product 1</div>
            <div class="product-card">Product 2</div>
            <a href="/product/1">Link 1</a>
        </body>
    </html>
    """
    inventory = build_signal_inventory(html, "https://example.com/products", "product_listing")

    assert len(inventory["structured_data"]["json_ld"]) > 0
    assert inventory["dom_patterns"]["card_count"] >= 0
    assert inventory["metadata"]["link_count"] >= 0


def test_classify_listing_page_with_json_ld():
    """Test classification of listing page based on JSON-LD."""
    inventory = _make_inventory(json_ld=[{"@type": "ItemList"}])

    page_type = classify_page_type(inventory)
    assert page_type == "listing"


def test_classify_detail_page_with_json_ld():
    """Test classification of detail page based on JSON-LD."""
    inventory = _make_inventory(json_ld=[{"@type": "Product"}])

    page_type = classify_page_type(inventory)
    assert page_type == "detail"


def test_classify_listing_page_with_card_count():
    """Test classification of listing page based on card count."""
    inventory = _make_inventory(card_count=10)

    page_type = classify_page_type(inventory)
    assert page_type == "listing"


def test_classify_detail_page_with_markers():
    """Test classification of detail page based on DOM markers."""
    inventory = _make_inventory(has_price=True, has_description=True)

    page_type = classify_page_type(inventory)
    assert page_type == "detail"


def test_classify_unknown_page():
    """Test classification of unknown page with no clear signals."""
    inventory = _make_inventory()

    page_type = classify_page_type(inventory)
    assert page_type == "unknown"


def test_classify_does_not_infer_from_surface_metadata():
    """Surface metadata should not drive page classification."""
    inventory = _make_inventory(link_count=1, text_ratio=0.1, surface="ecommerce_detail")
    assert classify_page_type(inventory) == "unknown"
