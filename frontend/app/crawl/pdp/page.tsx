import { redirect } from "next/navigation";

export default function PdpCrawlPage() {
 redirect("/crawl?module=pdp&mode=single");
}
