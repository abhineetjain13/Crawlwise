"""Discover stage — page-source discovery owner.

Owns parsing of rendered HTML into the structured-source inventory that
the extract stage consumes. Consumers import from this package rather
than reaching into extract for source parsing.
"""

from __future__ import annotations

from app.services.discover.page_sources import (
    extract_apollo_state_from_meta,
    extract_embedded_json,
    extract_hydrated_states,
    extract_json_ld,
    extract_microdata,
    extract_next_data,
    extract_open_graph,
    extract_tables,
    parse_datalayer,
    parse_page_sources,
    parse_page_sources_async,
)
from app.services.discover.signal_inventory import (
    HtmlSignalAnalysis,
    ListingSignalSummary,
    analyze_html_signals,
    assess_extractable_html,
    find_promotable_iframe_sources,
    html_has_extractable_listings,
    html_has_min_listing_link_signals,
)
from app.services.discover.network_inventory import collect_network_payload_candidates
from app.services.discover.state_inventory import (
    discover_listing_items,
    map_state_fields,
)

__all__ = [
    "extract_apollo_state_from_meta",
    "extract_embedded_json",
    "extract_hydrated_states",
    "extract_json_ld",
    "extract_microdata",
    "extract_next_data",
    "extract_open_graph",
    "extract_tables",
    "HtmlSignalAnalysis",
    "ListingSignalSummary",
    "analyze_html_signals",
    "assess_extractable_html",
    "collect_network_payload_candidates",
    "discover_listing_items",
    "find_promotable_iframe_sources",
    "html_has_extractable_listings",
    "html_has_min_listing_link_signals",
    "map_state_fields",
    "parse_datalayer",
    "parse_page_sources",
    "parse_page_sources_async",
]
