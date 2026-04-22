function normalizeApiTimestamp(value: string) {
 const trimmed = String(value ||"").trim();
 if (!trimmed) {
 return trimmed;
 }
 // Backend may emit UTC timestamps without timezone suffix.
 if (/[zZ]$/.test(trimmed) || /[+-]\d{2}:\d{2}$/.test(trimmed)) {
 return trimmed;
 }
 return `${trimmed}Z`;
}

export function parseApiDate(value: string) {
 return new Date(normalizeApiTimestamp(value));
}

export function formatRunsDate(value: string) {
 const date = parseApiDate(value);
 if (Number.isNaN(date.getTime())) return value;
 return date.toLocaleString("en-US", {
 month:"short",
 day:"2-digit",
 hour:"2-digit",
 minute:"2-digit",
 timeZone:"UTC",
 });
}

export function formatJobsTimestamp(value: string) {
 const date = parseApiDate(value);
 if (Number.isNaN(date.getTime())) {
 return value;
 }
 return date.toLocaleString([], {
 month:"short",
 day:"numeric",
 hour:"2-digit",
 minute:"2-digit",
 });
}

export function formatAdminUserDate(value: string) {
 const date = parseApiDate(value);
 if (Number.isNaN(date.getTime())) {
 return value;
 }
 return date.toLocaleString([], {
 month:"short",
 day:"numeric",
 year:"numeric",
 hour:"2-digit",
 minute:"2-digit",
 });
}

export function formatTimeHms(value: string) {
 const date = parseApiDate(value);
 if (Number.isNaN(date.getTime())) {
 return value;
 }
 return date.toLocaleTimeString([], {
 hour:"2-digit",
 minute:"2-digit",
 second:"2-digit",
 });
}

export function formatNowHms() {
 return formatTimeHms(new Date().toISOString());
}
