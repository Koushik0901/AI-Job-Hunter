import type { AutofillProfile } from "../api";

export interface FillResult {
  filled: number;
  skipped: number;
  fields: string[];
}

export interface AtsModule {
  detectForm(): boolean;
  fillForm(profile: AutofillProfile): FillResult;
}
