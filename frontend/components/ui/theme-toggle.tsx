"use client";

import { Moon, Sun } from"lucide-react";
import { useSyncExternalStore } from"react";

import { cn } from"../../lib/utils";

type ThemeMode ="light"|"dark";
const THEME_STORAGE_KEY ="crawlerai-theme";
const THEME_TRANSITION_ATTR ="data-theme-transition";

export function ThemeToggle({ compact }: Readonly<{ compact?: boolean }>) {
 const theme = useSyncExternalStore(subscribeTheme, readTheme, () =>"light");

 function toggleTheme() {
 const next = theme ==="dark"?"light":"dark";
 applyTheme(next);
 }

 return (
 <button
 type="button"
 onClick={toggleTheme}
 className={cn(
"btn btn-secondary btn-icon focus-ring",
 compact ?"btn-sm":"btn-lg",
 )}
 aria-label="Toggle color theme"
 title={theme ==="dark"?"Switch to light mode":"Switch to dark mode"}
 >
 {theme ==="dark"? (
 <Sun className={compact ?"size-3.5":"size-4"} strokeWidth={2} aria-hidden />
 ) : (
 <Moon className={compact ?"size-3.5":"size-4"} strokeWidth={2} aria-hidden />
 )}
 </button>
 );
}

function readTheme(): ThemeMode {
 if (typeof document ==="undefined") {
 return"light";
 }
 return document.documentElement.dataset.theme ==="dark"?"dark":"light";
}

function applyTheme(value: string | null | undefined) {
 const nextTheme: ThemeMode = value ==="dark"?"dark":"light";
 const root = document.documentElement;
 root.setAttribute(THEME_TRANSITION_ATTR,"true");
 root.dataset.theme = nextTheme;
 window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
 window.requestAnimationFrame(() => {
 window.requestAnimationFrame(() => {
 root.removeAttribute(THEME_TRANSITION_ATTR);
 });
 });
}

function subscribeTheme(onStoreChange: () => void) {
 if (typeof window ==="undefined") {
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
