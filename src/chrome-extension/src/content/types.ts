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

export interface FieldProposal {
  key: string;     // internal key, e.g. "email"
  label: string;   // display label, e.g. "Email"
  value: string;   // effective value (correction > profile)
  found: boolean;  // whether a matching input was located on page
}

export interface ScanResult {
  ats_host: string;
  fields: FieldProposal[];
}
