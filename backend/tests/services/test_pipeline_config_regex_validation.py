from __future__ import annotations

import pytest


def test_extraction_rules_raises_descriptive_error_for_invalid_editorial_pattern():
    import re

    from app.services.config.extraction_rules import _compile_extraction_rule_patterns

    with pytest.raises(re.error):
        _compile_extraction_rule_patterns(["("])
