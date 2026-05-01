import { Card } from '../../../components/ui/primitives';

export default function LoadingRunDetailPage() {
  return (
    <div className="page-stack" aria-busy="true">
      <div role="status" aria-live="polite" className="sr-only">
        Loading content
      </div>
      <div className="space-y-2" aria-hidden="true">
        <div className="bg-panel h-8 w-56 animate-pulse rounded-md" />
        <div className="bg-panel h-4 w-80 animate-pulse rounded-md" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Card key={index} className="bg-panel h-20 animate-pulse" aria-hidden="true">
            <div />
          </Card>
        ))}
      </div>
      <Card className="bg-panel h-80 animate-pulse" aria-hidden="true">
        <div />
      </Card>
    </div>
  );
}
