"use client";

export default function AdminLlmPage() {
  return (
    <div className="space-y-6">
      <div className="bg-panel rounded-xl shadow-card backdrop-blur-md p-6">
        <h1 className="text-xl font-bold tracking-tighter text-primary">LLM Runtime Removed</h1>
        <p className="mt-3 max-w-3xl text-sm leading-[1.55] text-muted">
          Crawl execution no longer depends on runtime LLM configuration, provider
          catalogs, connection tests, or cost logging.
        </p>
        <p className="mt-2 max-w-3xl text-sm leading-[1.55] text-muted">
          Any future LLM-assisted workflows need to live outside the active crawl
          pipeline as offline tooling.
        </p>
      </div>
    </div>
  );
}
