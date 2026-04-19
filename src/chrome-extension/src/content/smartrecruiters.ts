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
  tryFill('input[name="phoneNumber"]', profile.phone, "phone");

  // LinkedIn via label text
  if (profile.linkedin_url) {
    const li = findInputByLabelText("linkedin");
    if (li && !li.value) {
      fillField(li, profile.linkedin_url);
      result.filled++;
      result.fields.push("linkedin");
    }
  }

  // Location via label text
  if (profile.city) {
    const loc = findInputByLabelText("location") || findInputByLabelText("city");
    if (loc && !loc.value) {
      fillField(loc, profile.city);
      result.filled++;
      result.fields.push("location");
    }
  }

  // Supplement with generic fill for any remaining fields
  const generic = genericFill(profile);
  result.filled += generic.filled;
  result.fields.push(...generic.fields);

  return result;
}
