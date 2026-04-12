from __future__ import annotations

from typing import TypedDict, TypeAlias


class VariantCandidateRow(TypedDict, total=False):
    value: object
    source: str
    payload_type: str
    payload_key: str
    payload_index: int
    payload_url: str


VariantCandidateRows: TypeAlias = list[VariantCandidateRow]
VariantCandidateRowMap: TypeAlias = dict[str, VariantCandidateRows]

VariantOptionValues: TypeAlias = dict[str, str]
VariantAxisValues: TypeAlias = dict[str, list[str]]
VariantProductAttributes: TypeAlias = dict[str, object]


class VariantRecord(TypedDict, total=False):
    variant_id: str
    sku: str
    price: str
    original_price: str
    availability: str
    image_url: str
    color: str
    size: str
    url: str
    available: bool
    option_values: VariantOptionValues


VariantRecords: TypeAlias = list[VariantRecord]


class VariantBundle(TypedDict, total=False):
    variants: VariantRecords
    variant_axes: VariantAxisValues
    product_attributes: VariantProductAttributes
    selected_variant: VariantRecord


class ScoredVariantBundle(VariantBundle, total=False):
    selection_score: int


class ParsedDemandwareVariantPayload(TypedDict):
    axis_values: VariantAxisValues
    selected_variant: VariantRecord
    selection_score: int
