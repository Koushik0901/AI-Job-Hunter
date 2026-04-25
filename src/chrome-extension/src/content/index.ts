/**
 * Content script entry point.
 * Detects which ATS we're on, listens for fill messages from the popup/background,
 * and runs the appropriate form filler. Also handles file upload via DataTransfer.
 */

import { getCachedProfile, getCorrections } from "../api";
import type { FillResult, FieldProposal, ScanResult } from "./types";
import { fillField, findInputByLabelText, uploadArtifactToFileInput } from "./utils";
import * as greenhouse from "./greenhouse";
import * as lever from "./lever";
import * as ashby from "./ashby";
import * as workable from "./workable";
import * as smartrecruiters from "./smartrecruiters";
import * as generic from "./generic";

const MODULES = [greenhouse, lever, ashby, workable, smartrecruiters, generic];

function detectModule() {
  for (const mod of MODULES) {
    if (mod.detectForm()) return mod;
  }
  return generic;
}

// Field definitions: key, label, keywords to match page labels, profile accessor
const FIELD_DEFS: Array<{
  key: string;
  label: string;
  keywords: string[];
  getProfileValue: (p: NonNullable<Awaited<ReturnType<typeof getCachedProfile>>>) => string | null | undefined;
}> = [
  { key: "full_name", label: "Full Name", keywords: ["full name", "your name", "name"], getProfileValue: (p) => p.full_name },
  { key: "email", label: "Email", keywords: ["email", "e-mail"], getProfileValue: (p) => p.email },
  { key: "phone", label: "Phone", keywords: ["phone", "mobile", "telephone"], getProfileValue: (p) => p.phone },
  { key: "linkedin_url", label: "LinkedIn URL", keywords: ["linkedin"], getProfileValue: (p) => p.linkedin_url },
  { key: "portfolio_url", label: "Portfolio / GitHub", keywords: ["portfolio", "website", "personal site"], getProfileValue: (p) => p.portfolio_url },
  { key: "city", label: "City", keywords: ["city", "current city"], getProfileValue: (p) => p.city },
  { key: "country", label: "Country", keywords: ["country"], getProfileValue: (p) => p.country },
];

const FIELD_KEYWORDS: Record<string, string[]> = Object.fromEntries(
  FIELD_DEFS.map((d) => [d.key, d.keywords]),
);

async function scanFields(): Promise<ScanResult> {
  const atsHost = location.host;
  const [profile, corrections] = await Promise.all([
    getCachedProfile(),
    getCorrections(atsHost),
  ]);

  if (!profile) return { ats_host: atsHost, fields: [] };

  const fields: FieldProposal[] = [];
  for (const def of FIELD_DEFS) {
    const profileValue = def.getProfileValue(profile) || "";
    const value = corrections[def.key] ?? profileValue;
    if (!value) continue;
    let found = false;
    for (const kw of def.keywords) {
      if (findInputByLabelText(kw)) { found = true; break; }
    }
    fields.push({ key: def.key, label: def.label, value, found });
  }
  return { ats_host: atsHost, fields };
}

function fillConfirmedFields(confirmedValues: Record<string, string>): FillResult {
  const result: FillResult = { filled: 0, skipped: 0, fields: [] };
  for (const [key, value] of Object.entries(confirmedValues)) {
    if (!value) continue;
    const keywords = FIELD_KEYWORDS[key] || [key];
    let filled = false;
    for (const kw of keywords) {
      const input = findInputByLabelText(kw);
      if (input) {
        fillField(input, value);
        result.filled++;
        result.fields.push(key);
        filled = true;
        break;
      }
    }
    if (!filled) result.skipped++;
  }
  return result;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "SCAN_FIELDS") {
    scanFields().then((result) => sendResponse(result));
    return true;
  }

  if (message.type === "DO_FILL_FIELDS") {
    const confirmed = (message.confirmedValues || {}) as Record<string, string>;
    const result = fillConfirmedFields(confirmed);
    (async () => {
      if (message.resumeArtifactId) {
        const ok = await uploadArtifactToFileInput(message.resumeArtifactId as number, "resume");
        if (ok) { result.filled++; result.fields.push("resume_file"); }
      }
      if (message.coverLetterArtifactId) {
        const ok = await uploadArtifactToFileInput(message.coverLetterArtifactId as number, "cover_letter");
        if (ok) { result.filled++; result.fields.push("cover_letter_file"); }
      }
      sendResponse({ ok: true, ...result });
    })();
    return true;
  }

  if (message.type === "DO_AUTOFILL") {
    (async () => {
      const profile = await getCachedProfile();
      if (!profile) {
        sendResponse({ ok: false, error: "Could not load profile from dashboard. Is the backend running?" });
        return;
      }
      const mod = detectModule();
      let result: FillResult;
      try {
        result = mod.fillForm(profile);
      } catch (err) {
        sendResponse({ ok: false, error: String(err) });
        return;
      }
      if (message.resumeArtifactId) {
        const ok = await uploadArtifactToFileInput(message.resumeArtifactId as number, "resume");
        if (ok) { result.filled++; result.fields.push("resume_file"); }
      }
      if (message.coverLetterArtifactId) {
        const ok = await uploadArtifactToFileInput(message.coverLetterArtifactId as number, "cover_letter");
        if (ok) { result.filled++; result.fields.push("cover_letter_file"); }
      }
      sendResponse({ ok: true, filled: result.filled, fields: result.fields });
    })();
    return true;
  }
});

// Inject a small visible indicator so the user knows the extension is active
function injectReadyBadge(): void {
  if (document.getElementById("ajh-ready-badge")) return;
  const badge = document.createElement("div");
  badge.id = "ajh-ready-badge";
  badge.textContent = "AJH Autofill ready";
  Object.assign(badge.style, {
    position: "fixed",
    bottom: "16px",
    right: "16px",
    background: "#7f56d9",
    color: "#fff",
    padding: "6px 14px",
    borderRadius: "999px",
    fontSize: "12px",
    fontWeight: "600",
    fontFamily: "system-ui, sans-serif",
    zIndex: "2147483647",
    boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
    opacity: "0.92",
    pointerEvents: "none",
  });
  document.body.appendChild(badge);
  setTimeout(() => badge.remove(), 3000);
}

if (detectModule() !== generic || generic.detectForm()) {
  injectReadyBadge();
}
