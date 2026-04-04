"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function BulkCrawlPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/crawl?module=pdp&mode=batch");
  }, [router]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-muted">
      Preparing bulk crawl...
    </div>
  );
}
