"use client";

export default function AdminLlmPage() {
  return (
    <div className="space-y-6">
      <div className="rounded-[var(--radius-xl)] border border-border bg-panel p-6 shadow-[var(--shadow-sm)]">
        <h1 className="text-2xl font-semibold tracking-tight">LLM Runtime Removed</h1>
        <p className="mt-3 max-w-3xl text-sm text-muted">
          Crawl execution no longer depends on runtime LLM configuration, provider
          catalogs, connection tests, or cost logging.
        </p>
        <p className="mt-2 max-w-3xl text-sm text-muted">
          Any future LLM-assisted workflows need to live outside the active crawl
          pipeline as offline tooling.
        </p>
      </div>
    </div>
  );
}
