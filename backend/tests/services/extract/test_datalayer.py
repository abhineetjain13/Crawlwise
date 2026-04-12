# Property-based tests for dataLayer extraction
from __future__ import annotations

from app.services.extract.source_parsers import parse_datalayer
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Property 3: Extraction Hierarchy Order Preservation
# This property is tested in test_extract.py as it requires full extraction pipeline


# Property 4: dataLayer Parsing Round-Trip
@given(
    price=st.one_of(st.floats(min_value=0.01, max_value=10000.0), st.integers(min_value=1, max_value=10000)),
    currency=st.sampled_from(["USD", "EUR", "GBP", "JPY"]),
    category=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_datalayer_parsing_round_trip_ga4(price, currency, category):
    """Feature: extraction-pipeline-improvements, Property 4: dataLayer Parsing Round-Trip
    
    **Validates: Requirements 2.1, 2.2, 2.4**
    
    For any valid dataLayer ecommerce object (GA4 schema), if we extract fields using
    parse_datalayer(), the extracted values SHALL preserve the original price, availability,
    and currency information without loss or corruption.
    """
    # Create GA4 schema dataLayer HTML
    html = f"""
    <html><body>
    <script>
    dataLayer.push({{
        "ecommerce": {{
            "items": [
                {{
                    "price": {price},
                    "currency": "{currency}",
                    "item_category": "{category}"
                }}
            ]
        }}
    }});
    </script>
    </body></html>
    """
    
    result = parse_datalayer(html)
    
    # Verify price is preserved
    assert "price" in result
    assert result["price"] == price
    
    # Verify currency is preserved
    assert "price_currency" in result
    assert result["price_currency"] == currency
    
    # Verify category is preserved
    assert "google_product_category" in result
    assert result["google_product_category"] == category


@given(
    price=st.one_of(st.floats(min_value=0.01, max_value=10000.0), st.integers(min_value=1, max_value=10000)),
    currency=st.sampled_from(["USD", "EUR", "GBP", "JPY"]),
    category=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N"))),
)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_datalayer_parsing_round_trip_ua(price, currency, category):
    """Feature: extraction-pipeline-improvements, Property 4: dataLayer Parsing Round-Trip (UA schema)
    
    **Validates: Requirements 2.1, 2.2, 2.4**
    
    For any valid dataLayer ecommerce object (UA schema), if we extract fields using
    parse_datalayer(), the extracted values SHALL preserve the original price, availability,
    and currency information without loss or corruption.
    """
    # Create UA schema dataLayer HTML
    html = f"""
    <html><body>
    <script>
    dataLayer.push({{
        "ecommerce": {{
            "currencyCode": "{currency}",
            "detail": {{
                "products": [
                    {{
                        "price": {price},
                        "category": "{category}"
                    }}
                ]
            }}
        }}
    }});
    </script>
    </body></html>
    """
    
    result = parse_datalayer(html)
    
    # Verify price is preserved
    assert "price" in result
    assert result["price"] == price
    
    # Verify currency is preserved
    assert "price_currency" in result
    assert result["price_currency"] == currency
    
    # Verify category is preserved
    assert "google_product_category" in result
    assert result["google_product_category"] == category


# Property 5: dataLayer Error Handling
@given(html=st.text(max_size=1000))
def test_datalayer_error_handling_no_datalayer(html):
    """Feature: extraction-pipeline-improvements, Property 5: dataLayer Error Handling
    
    **Validates: Requirement 2.6**
    
    For any HTML input without a dataLayer object, parse_datalayer() SHALL return
    an empty dict without raising exceptions.
    """
    # Filter out HTML that might accidentally contain valid dataLayer
    if "dataLayer" in html:
        return
    
    result = parse_datalayer(html)
    
    # Should return empty dict, not raise exception
    assert isinstance(result, dict)
    assert result == {}


def test_datalayer_error_handling_malformed_json():
    """Feature: extraction-pipeline-improvements, Property 5: dataLayer Error Handling
    
    **Validates: Requirement 2.6**
    
    For any HTML input with malformed JSON in the dataLayer, parse_datalayer() SHALL
    return an empty dict without raising exceptions.
    """
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 19.99,
                    "currency": "USD"
                    // Missing closing brace
            ]
        }
    });
    </script>
    </body></html>
    """
    
    result = parse_datalayer(html)
    
    # Should return empty dict, not raise exception
    assert isinstance(result, dict)
    assert result == {}


def test_datalayer_error_handling_no_ecommerce():
    """Feature: extraction-pipeline-improvements, Property 5: dataLayer Error Handling
    
    **Validates: Requirement 2.6**
    
    For any HTML input with dataLayer but no ecommerce data, parse_datalayer() SHALL
    return an empty dict.
    """
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "event": "pageview",
        "page": "/products"
    });
    </script>
    </body></html>
    """
    
    result = parse_datalayer(html)
    
    # Should return empty dict when no ecommerce data
    assert isinstance(result, dict)
    assert result == {}


def test_datalayer_skips_invalid_push_and_uses_next_valid_payload():
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 19.99,
                    "currency": "USD"
                    // malformed object on purpose
            ]
        }
    });
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 29.99,
                    "currency": "EUR",
                    "item_category": "Shoes"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == 29.99
    assert result["price_currency"] == "EUR"
    assert result["google_product_category"] == "Shoes"


def test_datalayer_keeps_first_valid_ecommerce_push_and_records_selected_index():
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "event": "view_item_list",
        "ecommerce": {
            "items": [
                {
                    "price": 19.99
                }
            ]
        }
    });
    dataLayer.push({
        "event": "view_item",
        "ecommerce": {
            "currencyCode": "USD",
            "detail": {
                "products": [
                    {
                        "price": 29.99,
                        "category": "Cameras",
                        "availability": "InStock"
                    }
                ]
            }
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == 19.99
    assert "price_currency" not in result
    assert "google_product_category" not in result
    assert "availability" not in result
    assert result["_selected_push_index"] == 0


def test_datalayer_parses_json_with_braces_inside_string_values():
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": 9.99,
                    "currency": "USD",
                    "item_category": "Accessories",
                    "text": "this is a { test } string"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == 9.99
    assert result["price_currency"] == "USD"
    assert result["google_product_category"] == "Accessories"


def test_datalayer_does_not_compute_sale_price_when_price_parse_fails() -> None:
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": "not-a-number",
                    "discount": "5",
                    "currency": "USD"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == "not-a-number"
    assert result["discount_amount"] == "5"
    assert "sale_price" not in result


def test_datalayer_treats_large_price_numeric_discount_as_percentage() -> None:
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": "1799",
                    "discount": "40",
                    "currency": "INR"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == "1799"
    assert result["discount_percentage"] == "40"
    assert "discount_amount" not in result
    assert "sale_price" not in result


def test_datalayer_treats_plain_numeric_discount_as_amount_without_currency_context_when_large_relative_to_price() -> None:
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": "80",
                    "discount": "40"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == "80"
    assert result["discount_amount"] == "40"
    assert result["sale_price"] == 40
    assert "discount_percentage" not in result


def test_datalayer_does_not_assume_plain_numeric_discount_is_percentage_for_jpy() -> None:
    html = """
    <html><body>
    <script>
    dataLayer.push({
        "ecommerce": {
            "items": [
                {
                    "price": "12000",
                    "discount": "40",
                    "currency": "JPY"
                }
            ]
        }
    });
    </script>
    </body></html>
    """

    result = parse_datalayer(html)

    assert result["price"] == "12000"
    assert result["price_currency"] == "JPY"
    assert result["discount_amount"] == "40"
    assert result["sale_price"] == 11960
    assert "discount_percentage" not in result
