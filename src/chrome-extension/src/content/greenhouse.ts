import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, genericFill } from "./utils";

export function detectForm(): boolean {
  return Boolean(
    document.querySelector('form[action*="/applications"]') ||
    document.querySelector('#application_form') ||
    document.querySelector('input[name="job_application[first_name]"]')
  );
}

export function fillForm(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  function tryFill(selector: string, value: string | null | undefined): void {
    if (!value) { result.skipped++; return; }
    const el = document.querySelector<HTMLInputElement>(selector);
    if (!el || el.value) { result.skipped++; return; }
    fillField(el, value);
    result.filled++;
    result.fields.push(selector);
  }

  // Greenhouse standard field names
  tryFill('input[name="job_application[first_name]"]', profile.first_name);
  tryFill('input[name="job_application[last_name]"]', profile.last_name);
  tryFill('input[name="job_application[email]"]', profile.email);
  tryFill('input[name="job_application[phone]"]', profile.phone);
  tryFill('input[name="job_application[location]"]', profile.city);

  // LinkedIn, GitHub, and website (custom questions — Greenhouse uses id/placeholder hints)
  const linkedinEl = document.querySelector<HTMLInputElement>('input[id*="linkedin"], input[placeholder*="linkedin" i]');
  if (linkedinEl && !linkedinEl.value && profile.linkedin_url) {
    fillField(linkedinEl, profile.linkedin_url);
    result.filled++;
    result.fields.push("linkedin");
  }

  const githubEl = document.querySelector<HTMLInputElement>('input[id*="github"], input[placeholder*="github" i], input[name*="github" i]');
  if (githubEl && !githubEl.value && profile.github_url) {
    fillField(githubEl, profile.github_url);
    result.filled++;
    result.fields.push("github");
  }

  const websiteEl = document.querySelector<HTMLInputElement>('input[id*="website"], input[placeholder*="website" i], input[placeholder*="portfolio" i]');
  if (websiteEl && !websiteEl.value && profile.portfolio_url) {
    fillField(websiteEl, profile.portfolio_url);
    result.filled++;
    result.fields.push("website");
  }

  // Fall back to generic label matching for anything not already covered
  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.skipped += generic.skipped;
  result.fields.push(...generic.fields);

  return result;
}
