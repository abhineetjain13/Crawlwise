"use client";

import { useSearchParams } from"next/navigation";

import { CrawlConfigScreen } from"../../components/crawl/crawl-config-screen";
import { CrawlRunScreen } from"../../components/crawl/crawl-run-screen";
import {
 parseRequestedCategoryMode,
 parseRequestedCrawlTab,
 parseRequestedPdpMode,
} from"../../components/crawl/shared";

export default function CrawlPage() {
 const searchParams = useSearchParams();
 const runId = Number(searchParams.get("run_id") || searchParams.get("runId") || 0) || null;

 if (runId !== null) {
 return <CrawlRunScreen key={runId} runId={runId} />;
 }

 return (
 <CrawlConfigScreen
 requestedTab={parseRequestedCrawlTab(searchParams.get("module"))}
 requestedCategoryMode={parseRequestedCategoryMode(searchParams.get("mode"))}
 requestedPdpMode={parseRequestedPdpMode(searchParams.get("mode"))}
 />
 );
}
