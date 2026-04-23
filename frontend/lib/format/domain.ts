// Fallback policy: preserve the original input when parsing fails.
export function getDomain(url: string) {
 try {
 return new URL(url).hostname;
 } catch {
 return url;
 }
}

export function getNormalizedDomain(url: string) {
 try {
 return new URL(url).hostname.replace(/^www\./,"").toLowerCase();
 } catch {
 return url;
 }
}

const SPECIAL_USE_HOSTNAMES = new Set([
 "localhost",
 "localhost.localdomain",
]);

const SPECIAL_USE_SUFFIXES = [
 ".example",
 ".invalid",
 ".local",
 ".localhost",
];

export function isSpecialUseDomain(value: string) {
 const normalized = getNormalizedDomain(value).trim().toLowerCase();
 const host = normalized.startsWith("[")
 ? (() => {
 const closingIndex = normalized.indexOf("]");
 return closingIndex >= 0 ? normalized.slice(0, closingIndex + 1) : normalized;
 })()
 : normalized.replace(/:\d+$/, "");
 if (!host) {
 return true;
 }
 return SPECIAL_USE_HOSTNAMES.has(host) || SPECIAL_USE_SUFFIXES.some((suffix) => host.endsWith(suffix));
}
