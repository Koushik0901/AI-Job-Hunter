import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { fillField, findInputByLabelText, genericFill } from "./utils";

export function detectForm(): boolean {
  return !!(
    document.querySelector('input[name="firstName"]') ||
    document.querySelector('[data-testid="apply-form"]') ||
    document.querySelector(".smart-apply") ||
    document.querySelector('input[name="lastName"]')
  );
}

export function fillForm(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  function tryFill(selector: string, value: string | null | undefined, fieldName: string) {
    if (!value) return;
    const el = document.querySelector<HTMLInputElement>(selector);
    if (el && !el.value) {
      fillField(el, value);
      result.filled++;
      result.fields.push(fieldName);
    }
  }

  tryFill('input[name="firstName"]', profile.first_name, "firstName");
  tryFill('input[name="lastName"]', profile.last_name, "lastName");
  tryFill('input[name="email"]', profile.email, "email");
  tryFill('input[name="phone"]', profile.phone, "phone");
  tryFill('input[name="phoneNumber"]', profile.phone, "phoneNumber");
  // SmartRecruiters structured address fields
  tryFill('input[name="address.line1"]', profile.street_address, "address.line1");
  tryFill('input[name="address.line2"]', profile.address_line2, "address.line2");
  tryFill('input[name="address.city"]', profile.city, "address.city");
  tryFill('input[name="address.region"]', profile.state_province, "address.region");
  tryFill('input[name="address.postalCode"]', profile.postal_code, "address.postalCode");

  // Labels for things not in structured fields
  function tryLabel(text: string, value: string | null | undefined, key: string) {
    if (!value) return;
    const el = findInputByLabelText(text);
    if (el && !el.value) {
      fillField(el, value);
      result.filled++;
      result.fields.push(key);
    }
  }

  tryLabel("linkedin", profile.linkedin_url, "linkedin");
  tryLabel("github", profile.github_url, "github");
  tryLabel("website", profile.portfolio_url, "website");
  tryLabel("location", profile.city, "location");
  tryLabel("city", profile.city, "city");
  tryLabel("salary", profile.desired_salary, "salary");
  tryLabel("compensation", profile.desired_salary, "compensation");

  // Supplement with generic fill for any remaining fields
  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.fields.push(...generic.fields);

  return result;
}
