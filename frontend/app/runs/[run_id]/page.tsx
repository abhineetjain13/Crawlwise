import { redirect } from "next/navigation";

/**
 * Legacy run detail route — redirects to the crawl studio which has
 * the full two-column view, markdown tab, and review flow.
 */
export default async function RunDetailRedirect({
  params,
}: Readonly<{
  params: Promise<{ run_id: string }> | { run_id: string };
}>) {
  const resolvedParams = await params;
  redirect(`/crawl?run_id=${encodeURIComponent(resolvedParams.run_id)}`);
}
