from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_adp_detail_url(url: str | None) -> str | None:
    parsed = urlparse(str(url or "").strip())
    hostname = str(parsed.hostname or "").lower()
    if hostname not in {
        "workforcenow.adp.com",
        "myjobs.adp.com",
        "recruiting.adp.com",
    }:
        return url
    if "recruitment/recruitment.html" not in parsed.path.lower():
        return url
    if parsed.fragment:
        return url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    job_id = " ".join(str(query.get("jobId") or "").split()).strip()
    if not job_id:
        return url
    normalized_pairs: list[tuple[str, str]] = []
    replaced_job_id = False
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "jobId":
            normalized_pairs.append((key, job_id))
            replaced_job_id = True
            continue
        normalized_pairs.append((key, value))
    if not replaced_job_id:
        normalized_pairs.append(("jobId", job_id))
    return urlunparse(parsed._replace(query=urlencode(normalized_pairs, doseq=True)))
