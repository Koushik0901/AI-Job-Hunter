import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, genericFill } from "./utils";

export function detectForm(): boolean {
  return Boolean(
    document.querySelector('[data-qa="btn-apply"]') ||
    document.querySelector('[data-qa="name"]') ||
    window.location.hostname.includes("jobs.lever.co")
  );
}

export function fillForm(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  function tryQa(qa: string, value: string | null | undefined): void {
    if (!value) { result.skipped++; return; }
    const el = document.querySelector<HTMLInputElement>(`[data-qa="${qa}"]`);
    if (!el || el.value) { result.skipped++; return; }
    fillField(el, value);
    result.filled++;
    result.fields.push(qa);
  }

  // Lever uses data-qa attributes on application form inputs
  tryQa("name", profile.full_name);
  tryQa("email", profile.email);
  tryQa("phone", profile.phone);
  tryQa("org", undefined); // current company — skip
  tryQa("linkedin", profile.linkedin_url);
  tryQa("twitter", undefined); // skip

  // Website / portfolio
  const websiteEl = document.querySelector<HTMLInputElement>('[data-qa="website"], [placeholder*="website" i], [placeholder*="portfolio" i]');
  if (websiteEl && !websiteEl.value && profile.portfolio_url) {
    fillField(websiteEl, profile.portfolio_url);
    result.filled++;
    result.fields.push("website");
  }

  // GitHub (Lever sometimes adds as custom question)
  const githubEl = document.querySelector<HTMLInputElement>('[data-qa="github"], input[placeholder*="github" i], input[id*="github"]');
  if (githubEl && !githubEl.value && profile.github_url) {
    fillField(githubEl, profile.github_url);
    result.filled++;
    result.fields.push("github");
  }

  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.skipped += generic.skipped;
  result.fields.push(...generic.fields);

  return result;
}
