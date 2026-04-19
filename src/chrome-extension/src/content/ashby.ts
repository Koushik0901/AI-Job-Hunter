import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, findInputByLabelText, genericFill } from "./utils";

export function detectForm(): boolean {
  return Boolean(
    window.location.hostname.includes("jobs.ashbyhq.com") ||
    document.querySelector('form[data-ashby]') ||
    document.querySelector('[class*="ashby"]')
  );
}

export function fillForm(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  function tryLabel(labelText: string, value: string | null | undefined): void {
    if (!value) { result.skipped++; return; }
    const el = findInputByLabelText(labelText);
    if (!el || el.value) { result.skipped++; return; }
    fillField(el, value);
    result.filled++;
    result.fields.push(labelText);
  }

  // Ashby renders React forms — use label matching
  tryLabel("first name", profile.first_name);
  tryLabel("last name", profile.last_name);
  tryLabel("email", profile.email);
  tryLabel("phone", profile.phone);
  tryLabel("linkedin", profile.linkedin_url);
  tryLabel("website", profile.portfolio_url);
  tryLabel("portfolio", profile.portfolio_url);
  tryLabel("city", profile.city);
  tryLabel("location", profile.city);

  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.skipped += generic.skipped;
  result.fields.push(...generic.fields);

  return result;
}
