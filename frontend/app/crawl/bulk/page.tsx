import { redirect } from 'next/navigation';

export default function BulkCrawlPage() {
  redirect('/crawl?module=pdp&mode=batch');
}
