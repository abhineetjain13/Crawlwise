"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";

export default function SelectorsPage() {
  const { data } = useQuery({ queryKey: ["selectors"], queryFn: () => api.listSelectors() });
  const selectors = data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="Selectors" description="Saved selector memory and defaults." />
      <Card className="space-y-4">
        <SectionHeader title="Memory" description="XPath-first selector memory used by review and extraction." />
        {selectors.length ? (
          <div className="overflow-auto rounded-md border border-border">
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Field</th>
                  <th>XPath</th>
                  <th>CSS</th>
                  <th>Status</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {selectors.map((selector) => (
                  <tr key={selector.id}>
                    <td>{selector.domain}</td>
                    <td>{selector.field_name}</td>
                    <td title={selector.xpath ?? ""}><span className="block max-w-[420px] truncate">{selector.xpath || "--"}</span></td>
                    <td title={selector.css_selector ?? ""}><span className="block max-w-[280px] truncate">{selector.css_selector || "--"}</span></td>
                    <td>{selector.status}</td>
                    <td>{selector.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[13px] text-muted">No selector memory saved yet.</p>
        )}
      </Card>
    </div>
  );
}
