import { getDashboardUrl } from "../api";
import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";

/** Simulate human-like typing into an input field and trigger React/Vue change events. */
export function fillField(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  const nativeTextareaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;

  if (el instanceof HTMLInputElement && nativeInputValueSetter) {
    nativeInputValueSetter.call(el, value);
  } else if (el instanceof HTMLTextAreaElement && nativeTextareaValueSetter) {
    nativeTextareaValueSetter.call(el, value);
  } else {
    el.value = value;
  }

  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
}

export function fillSelect(el: HTMLSelectElement, value: string): void {
  el.value = value;
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/** Find a label element by case-insensitive text match and return its associated input. */
export function findInputByLabelText(text: string): HTMLInputElement | HTMLTextAreaElement | null {
  const labels = Array.from(document.querySelectorAll<HTMLLabelElement>("label"));
  const target = text.toLowerCase();
  const label = labels.find((l) => l.textContent?.toLowerCase().includes(target));
  if (!label) return null;

  if (label.htmlFor) {
    const el = document.getElementById(label.htmlFor);
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return el;
  }

  const child = label.querySelector<HTMLInputElement | HTMLTextAreaElement>("input, textarea");
  if (child) return child;

  const next = label.nextElementSibling;
  if (next instanceof HTMLInputElement || next instanceof HTMLTextAreaElement) return next;

  return null;
}

/**
 * Generic label-text heuristic filler.
 * Maps common label keywords to profile fields.
 */
export function genericFill(profile: AutofillProfile): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };

  const fieldMap: Array<[string[], string | null | undefined]> = [
    [["first name", "firstname", "given name"], profile.first_name],
    [["last name", "lastname", "surname", "family name"], profile.last_name],
    [["full name", "your name", "name"], profile.full_name],
    [["email", "e-mail"], profile.email],
    [["phone", "mobile", "telephone"], profile.phone],
    [["linkedin", "linkedin url", "linkedin profile"], profile.linkedin_url],
    [["portfolio", "website", "personal website", "personal site"], profile.portfolio_url],
    [["city", "current city"], profile.city],
    [["country"], profile.country],
  ];

  for (const [keywords, value] of fieldMap) {
    if (!value) continue;
    for (const keyword of keywords) {
      const input = findInputByLabelText(keyword);
      if (input && !input.value) {
        fillField(input, value);
        result.filled++;
        result.fields.push(keyword);
        break;
      }
    }
  }

  return result;
}

/**
 * Find a file input element likely associated with the given document type.
 */
export function findFileInput(type: "resume" | "cover_letter"): HTMLInputElement | null {
  const keywords =
    type === "resume"
      ? ["resume", "cv", "curriculum"]
      : ["cover", "letter", "coverletter", "cover_letter"];

  for (const kw of keywords) {
    const el = document.querySelector<HTMLInputElement>(
      `input[type="file"][name*="${kw}"], input[type="file"][id*="${kw}"], input[type="file"][accept*="${kw}"]`
    );
    if (el) return el;
  }
  // Fallback: first file input on page
  return document.querySelector<HTMLInputElement>('input[type="file"]');
}

/**
 * Fetch a PDF artifact from the dashboard and inject it into the matching file input.
 * Uses DataTransfer API — no user download needed.
 */
export async function uploadArtifactToFileInput(
  artifactId: number,
  type: "resume" | "cover_letter"
): Promise<boolean> {
  const base = await getDashboardUrl();
  try {
    const resp = await fetch(`${base}/api/artifacts/${artifactId}/pdf`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!resp.ok) return false;

    const blob = await resp.blob();
    const filename = type === "resume" ? "resume.pdf" : "cover_letter.pdf";
    const file = new File([blob], filename, { type: "application/pdf" });

    const input = findFileInput(type);
    if (!input) return false;

    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  } catch {
    return false;
  }
}
