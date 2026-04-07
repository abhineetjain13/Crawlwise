import { Card } from "../../../components/ui/primitives";

/**
 * Renders a loading skeleton for the run detail page while content is being fetched.
 * @example
 * LoadingRunDetailPage()
 * <div className="space-y-4" aria-busy="true">...</div>
 * @returns {JSX.Element} The loading placeholder UI for the run detail page.
 */
export default function LoadingRunDetailPage() {
  return (
    <div className="space-y-4" aria-busy="true">
      <div role="status" aria-live="polite" className="sr-only">
        Loading content
      </div>
      <div className="space-y-2" aria-hidden="true">
        <div className="h-8 w-56 animate-pulse rounded-md bg-panel" />
        <div className="h-4 w-80 animate-pulse rounded-md bg-panel" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Card key={index} className="h-20 animate-pulse bg-panel" aria-hidden="true">
            <div />
          </Card>
        ))}
      </div>
      <Card className="h-80 animate-pulse bg-panel" aria-hidden="true">
        <div />
      </Card>
    </div>
  );
}
