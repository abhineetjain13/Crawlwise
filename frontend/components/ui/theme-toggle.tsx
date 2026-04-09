"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { cn } from "../../lib/utils";

type ThemeMode = "light" | "dark";
const THEME_STORAGE_KEY = "crawlerai-theme";

export function ThemeToggle({ compact }: Readonly<{ compact?: boolean }>) {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => "light");

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    applyTheme(next);
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={cn(
        "focus-ring inline-flex items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)]",
        "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-[var(--shadow-xs)] transition-all",
        "hover:bg-[var(--button-ghost-hover-bg)] hover:text-[var(--accent)]",
        compact ? "size-8" : "size-9",
      )}
      aria-label="Toggle color theme"
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? (
        <Sun className={compact ? "size-3.5" : "size-4"} strokeWidth={2} aria-hidden />
      ) : (
        <Moon className={compact ? "size-3.5" : "size-4"} strokeWidth={2} aria-hidden />
      )}
    </button>
  );
}

function readTheme(): ThemeMode {
  if (typeof document === "undefined") {
    return "light";
  }
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(value: string | null | undefined) {
  const nextTheme: ThemeMode = value === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = nextTheme;
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
}

function subscribeTheme(onStoreChange: () => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  const observer = new MutationObserver(onStoreChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });

  const storageHandler = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY) {
      return;
    }
    applyTheme(event.newValue ?? window.localStorage.getItem(THEME_STORAGE_KEY));
    onStoreChange();
  };

  window.addEventListener("storage", storageHandler);
  return () => {
    observer.disconnect();
    window.removeEventListener("storage", storageHandler);
  };
}
