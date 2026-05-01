"use client";

import { History, X } from "lucide-react";
import React, { useEffect } from "react";

import { Badge, Button } from "./primitives";
import { cn } from "../../lib/utils";

export type HistoryItem = {
  id: number;
  status: string;
  created_at: string;
  label?: string;
  meta?: string;
};

export function HistoryDrawer({
  open,
  onClose,
  items,
  activeId,
  onSelect,
  title = "Run History",
}: Readonly<{
  open: boolean;
  onClose: () => void;
  items: HistoryItem[];
  activeId?: number | null;
  onSelect: (id: number) => void;
  title?: string;
}>) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="fixed right-0 top-0 z-50 h-full w-[380px] max-w-full overflow-y-auto border-l border-divider bg-background-elevated p-0 shadow-xl animate-in slide-in-from-right-4 duration-200 flex flex-col">
        <div className="flex items-center justify-between border-b border-divider px-4 py-3">
          <div className="flex items-center gap-2">
            <History className="size-4 text-muted" />
            <h2 className="text-sm font-medium text-foreground type-heading">{title}</h2>
          </div>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="Close history">
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-auto">
          {items.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full p-8 text-center text-muted">
              <History className="size-8 opacity-20 mb-3" />
              <p className="text-xs">No history found.</p>
            </div>
          ) : (
            <table className="compact-data-table w-full">
              <tbody>
                {items.map((item) => (
                  <tr 
                    key={item.id} 
                    className={cn(
                      "border-b border-divider last:border-0 hover:bg-background-alt transition-colors cursor-pointer", 
                      activeId === item.id && "bg-background-alt"
                    )}
                    onClick={() => {
                      onSelect(item.id);
                      onClose();
                    }}
                  >
                    <td className="p-0">
                      <div className="flex w-full flex-col text-left gap-1.5 p-3.5">
                        <div className="flex w-full items-center justify-between">
                          <span className={cn(
                            "font-mono text-sm font-normal text-accent",
                            activeId === item.id && "font-bold"
                          )}>
                            #{item.id}
                          </span>
                          <Badge 
                            tone={
                              item.status === "complete" || item.status === "completed" || item.status === "success" 
                                ? "success" 
                                : item.status === "failed" || item.status === "error" 
                                  ? "danger" 
                                  : "neutral"
                            } 
                            className="scale-90 origin-right"
                          >
                            {item.status}
                          </Badge>
                        </div>
                        {item.label && (
                          <div className="text-xs font-medium text-foreground truncate max-w-[300px]">
                            {item.label}
                          </div>
                        )}
                        <div className="flex w-full items-center justify-between text-[10px] text-muted uppercase tracking-wider font-medium">
                          <span>{item.meta ?? "No details"}</span>
                          <span className="font-mono">{formatShortDate(item.created_at)}</span>
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

function formatShortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
