import type { AutofillProfile } from "../api";
import type { FillResult } from "./types";
import { genericFill } from "./utils";

export function detectForm(): boolean {
  return Boolean(document.querySelector("form"));
}

export function fillForm(profile: AutofillProfile): FillResult {
  return genericFill(profile);
}
