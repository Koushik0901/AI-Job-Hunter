import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, genericFill } from "./utils";

export function detectForm(): boolean {
  return Boolean(
    window.location.hostname.includes("apply.workable.com") ||
    document.querySelector('form[class*="workable"]') ||
    document.querySelector('input[name="firstname"]')
  );
}

export function fillForm(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  function tryName(name: string, value: string | null | undefined): void {
    if (!value) { result.skipped++; return; }
    const el = document.querySelector<HTMLInputElement>(`input[name="${name}"]`);
    if (!el || el.value) { result.skipped++; return; }
    fillField(el, value);
    result.filled++;
    result.fields.push(name);
  }

  tryName("firstname", profile.first_name);
  tryName("lastname", profile.last_name);
  tryName("email", profile.email);
  tryName("phone", profile.phone);

  // Workable sometimes uses placeholder-based fields for links
  const linkedinEl = document.querySelector<HTMLInputElement>('input[placeholder*="linkedin" i], input[name*="linkedin" i]');
  if (linkedinEl && !linkedinEl.value && profile.linkedin_url) {
    fillField(linkedinEl, profile.linkedin_url);
    result.filled++;
    result.fields.push("linkedin");
  }

  const websiteEl = document.querySelector<HTMLInputElement>('input[placeholder*="website" i], input[placeholder*="portfolio" i]');
  if (websiteEl && !websiteEl.value && profile.portfolio_url) {
    fillField(websiteEl, profile.portfolio_url);
    result.filled++;
    result.fields.push("website");
  }

  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.skipped += generic.skipped;
  result.fields.push(...generic.fields);

  return result;
}
