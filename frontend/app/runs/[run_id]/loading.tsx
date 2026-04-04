import { Card } from "../../../components/ui/primitives";

export default function LoadingRunDetailPage() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="h-8 w-56 animate-pulse rounded-md bg-panel" />
        <div className="h-4 w-80 animate-pulse rounded-md bg-panel" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Card key={index} className="h-20 animate-pulse bg-panel">
            <div />
          </Card>
        ))}
      </div>
      <Card className="h-80 animate-pulse bg-panel">
        <div />
      </Card>
    </div>
  );
}
