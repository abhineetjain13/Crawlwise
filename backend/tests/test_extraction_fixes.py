# Tests for size/color extraction fixes
import pytest
from bs4 import BeautifulSoup

from app.services.extract.listing_extractor import _extract_card_color


class TestColorExtraction:
    def test_color_from_data_attribute(self):
        html = '<div><span data-color="Red">Color</span></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = []
        
        result = _extract_card_color(card, lines)
        assert result == "Red"
    
    def test_color_from_aria_label(self):
        html = '<div><button aria-label="Blue">Select</button></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = []
        
        result = _extract_card_color(card, lines)
        assert result == "Blue"
    
    def test_color_with_colon_delimiter(self):
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = ["Color: Navy Blue"]
        
        result = _extract_card_color(card, lines)
        assert result == "Navy Blue"
    
    def test_color_filters_generic_phrases(self):
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = ["2 colors"]
        
        result = _extract_card_color(card, lines)
        # Should not return "2 colors"
        assert result == ""
    
    def test_color_filters_multiple_colors(self):
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = ["Colors: 5 colors"]
        
        result = _extract_card_color(card, lines)
        # Should not return "5 colors"
        assert result == ""
    
    def test_color_without_delimiter(self):
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = ["Color"]
        
        result = _extract_card_color(card, lines)
        # Should not return just "Color"
        assert result == ""
    
    def test_color_case_insensitive(self):
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        lines = ["COLOR: Black"]
        
        result = _extract_card_color(card, lines)
        assert result == "Black"


class TestSizeExtraction:
    """
    Note: Size extraction is tested indirectly through the full extraction pipeline.
    These tests verify the logic patterns used in the fix.
    """
    
    def test_size_pattern_with_colon(self):
        import re
        line = "Size: Large"
        match = re.search(r"(?i)sizes?\s*[:\-]\s*(.+)", line)
        assert match is not None
        assert match.group(1).strip() == "Large"
    
    def test_size_pattern_filters_generic(self):
        import re
        line = "Size: multiple sizes"
        match = re.search(r"(?i)sizes?\s*[:\-]\s*(.+)", line)
        assert match is not None
        size_value = match.group(1).strip()
        
        # Should be filtered out
        is_generic = re.match(r"^(multiple|various)\s+sizes?$", size_value, re.I)
        assert is_generic is not None
    
    def test_size_pattern_with_actual_sizes(self):
        import re
        line = "Size: S, M, L, XL"
        
        # Check if line contains actual size indicators
        has_sizes = re.search(r"\b(?:[SMLX]{1,3}|[0-9]+(?:\.[0-9]+)?(?:\s*(?:in|cm|mm|oz|lb|kg|g))?)\b", line, re.I)
        assert has_sizes is not None
    
    def test_size_pattern_with_measurements(self):
        import re
        line = "Size: 10.5 in"
        
        has_sizes = re.search(r"\b(?:[SMLX]{1,3}|[0-9]+(?:\.[0-9]+)?(?:\s*(?:in|cm|mm|oz|lb|kg|g))?)\b", line, re.I)
        assert has_sizes is not None
    
    def test_size_pattern_without_value(self):
        import re
        line = "Size"
        match = re.search(r"(?i)sizes?\s*[:\-]\s*(.+)", line)
        # Should not match
        assert match is None


class TestExtractionRegression:
    """Regression tests to ensure the bugs don't come back."""
    
    def test_color_not_literal_label(self):
        """Ensure we don't return literal 'Color' or '2 colors'."""
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        
        # Test case 1: Just the word "Color"
        result = _extract_card_color(card, ["Color"])
        assert result != "Color", "Should not return literal 'Color'"
        
        # Test case 2: "2 colors"
        result = _extract_card_color(card, ["2 colors"])
        assert result != "2 colors", "Should not return '2 colors'"
        
        # Test case 3: "Multiple colors"
        result = _extract_card_color(card, ["Multiple colors"])
        assert result != "Multiple colors", "Should not return 'Multiple colors'"
    
    def test_color_extracts_actual_value(self):
        """Ensure we DO extract actual color values."""
        html = '<div></div>'
        card = BeautifulSoup(html, "html.parser")
        
        # Test case 1: With colon
        result = _extract_card_color(card, ["Color: Navy Blue"])
        assert result == "Navy Blue", "Should extract actual color value"
        
        # Test case 2: With dash
        result = _extract_card_color(card, ["Color - Red"])
        assert result == "Red", "Should extract actual color value with dash"
