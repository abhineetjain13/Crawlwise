from __future__ import annotations


def as_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, bool)):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, (str, bytes)):
        raw_value = value.decode() if isinstance(value, bytes) else value
        raw_value = raw_value.strip()
        if not raw_value:
            return 0
        try:
            return int(raw_value)
        except ValueError:
            try:
                return int(float(raw_value))
            except ValueError:
                return 0
    return 0


def merge_url_verdicts(current: object, patch: object) -> list[str]:
    current_list = list(current) if isinstance(current, list) else []
    patch_list = list(patch) if isinstance(patch, list) else []
    max_len = max(len(current_list), len(patch_list))
    merged: list[str] = []
    for idx in range(max_len):
        patch_value = (
            str(patch_list[idx] or "").strip() if idx < len(patch_list) else ""
        )
        current_value = (
            str(current_list[idx] or "").strip() if idx < len(current_list) else ""
        )
        merged.append(patch_value or current_value)
    return merged


def merge_verdict_counts(current: object, patch: object) -> dict[str, int]:
    current_map = dict(current) if isinstance(current, dict) else {}
    patch_map = dict(patch) if isinstance(patch, dict) else {}
    keys = set(current_map) | set(patch_map)
    merged: dict[str, int] = {}
    for key in keys:
        merged[str(key)] = max(as_int(current_map.get(key)), as_int(patch_map.get(key)))
    return merged


def merge_run_summary_patch(
    current: object,
    patch: dict[str, object],
) -> dict[str, object]:
    summary = dict(current) if isinstance(current, dict) else {}
    merged = {**summary, **patch}

    for key in (
        "url_count",
        "record_count",
        "progress",
        "processed_urls",
        "completed_urls",
    ):
        if key in summary or key in patch:
            merged[key] = max(as_int(summary.get(key)), as_int(patch.get(key)))

    if "remaining_urls" in patch:
        prev_remaining = summary.get("remaining_urls")
        if prev_remaining is None:
            merged["remaining_urls"] = as_int(patch.get("remaining_urls"))
        else:
            merged["remaining_urls"] = min(
                as_int(prev_remaining),
                as_int(patch.get("remaining_urls")),
            )

    if "url_verdicts" in patch or "url_verdicts" in summary:
        merged["url_verdicts"] = merge_url_verdicts(
            summary.get("url_verdicts"),
            patch.get("url_verdicts"),
        )

    if "verdict_counts" in patch or "verdict_counts" in summary:
        merged["verdict_counts"] = merge_verdict_counts(
            summary.get("verdict_counts"),
            patch.get("verdict_counts"),
        )

    return merged
