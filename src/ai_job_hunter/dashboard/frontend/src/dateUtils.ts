const ISO_DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseDateLike(value: string | null | undefined): Date | null {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  const dateOnlyMatch = raw.match(ISO_DATE_ONLY);
  if (dateOnlyMatch) {
    const [, yearText, monthText, dayText] = dateOnlyMatch;
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    const localDate = new Date(year, month - 1, day);
    return Number.isNaN(localDate.valueOf()) ? null : localDate;
  }
  const parsed = new Date(raw);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

export function dateValueMs(value: string | null | undefined): number | null {
  const parsed = parseDateLike(value);
  return parsed ? parsed.valueOf() : null;
}

export function formatDateShort(value: string | null | undefined, fallback = "Unknown"): string {
  const parsed = parseDateLike(value);
  return parsed
    ? parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : ((value ?? "").trim() || fallback);
}

export function formatDateTime(value: string | null | undefined, fallback = "-"): string {
  const parsed = parseDateLike(value);
  return parsed ? parsed.toLocaleString() : ((value ?? "").trim() || fallback);
}
