import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, findInputByLabelText, genericFill } from "./utils";

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
  // Address fields (Workable uses name attributes for structured address)
  tryName("address1", profile.street_address);
  tryName("address2", profile.address_line2);
  tryName("city", profile.city);
  tryName("state", profile.state_province);
  tryName("province", profile.state_province);
  tryName("zip", profile.postal_code);
  tryName("zipcode", profile.postal_code);
  tryName("country", profile.country);

  // Links — Workable uses placeholder-based fields
  const linkedinEl = document.querySelector<HTMLInputElement>('input[placeholder*="linkedin" i], input[name*="linkedin" i]');
  if (linkedinEl && !linkedinEl.value && profile.linkedin_url) {
    fillField(linkedinEl, profile.linkedin_url);
    result.filled++;
    result.fields.push("linkedin");
  }

  const githubEl = document.querySelector<HTMLInputElement>('input[placeholder*="github" i], input[name*="github" i]');
  if (githubEl && !githubEl.value && profile.github_url) {
    fillField(githubEl, profile.github_url);
    result.filled++;
    result.fields.push("github");
  }

  const websiteEl = document.querySelector<HTMLInputElement>('input[placeholder*="website" i], input[placeholder*="portfolio" i]');
  if (websiteEl && !websiteEl.value && profile.portfolio_url) {
    fillField(websiteEl, profile.portfolio_url);
    result.filled++;
    result.fields.push("website");
  }

  // Salary via label matching
  if (profile.desired_salary) {
    const salaryEl = findInputByLabelText("salary") || findInputByLabelText("compensation");
    if (salaryEl && !salaryEl.value) {
      fillField(salaryEl, profile.desired_salary);
      result.filled++;
      result.fields.push("salary");
    }
  }

  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.skipped += generic.skipped;
  result.fields.push(...generic.fields);

  return result;
}
