import { redirect } from 'next/navigation';

export default function CategoryCrawlPage() {
  redirect('/crawl?module=category&mode=single');
}
