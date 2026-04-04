"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Legacy run detail route — redirects to the crawl studio which has
 * the full two-column view, intelligence tab, and review flow.
 */
export default function RunDetailRedirect() {
  const params = useParams<{ run_id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!params.run_id) {
      return;
    }
    router.replace(`/crawl?run_id=${params.run_id}`);
  }, [params.run_id, router]);

  return (
    <div className="flex items-center justify-center py-12 text-sm text-muted">
      Redirecting to crawl studio...
    </div>
  );
}
