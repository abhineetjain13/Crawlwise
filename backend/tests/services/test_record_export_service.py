from __future__ import annotations

import json

import pytest
from app.models.crawl import CrawlRecord
from app.services.record_export_service import stream_export_json


@pytest.mark.asyncio
async def test_stream_export_json_tolerates_non_dict_row_data(monkeypatch) -> None:
    row = CrawlRecord(id=9, run_id=1, source_url="https://example.com/item", data=None)

    async def _fake_stream(_session, _run_id):
        yield row

    monkeypatch.setattr(
        "app.services.record_export_service._stream_export_rows",
        _fake_stream,
    )

    chunks = []
    async for chunk in stream_export_json(object(), 1):
        chunks.append(chunk)

    assert json.loads("".join(chunks)) == [{}]
