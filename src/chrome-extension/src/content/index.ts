/**
 * Content script entry point.
 * Detects which ATS we're on, listens for fill messages from the popup/background,
 * and runs the appropriate form filler. Also handles file upload via DataTransfer.
 */

import { getCachedProfile } from "../api";
import type { FillResult } from "./types";
import { uploadArtifactToFileInput } from "./utils";
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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "DO_AUTOFILL") return;

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

    // Upload PDF artifacts if provided
    if (message.resumeArtifactId) {
      const ok = await uploadArtifactToFileInput(message.resumeArtifactId as number, "resume");
      if (ok) {
        result.filled++;
        result.fields.push("resume_file");
      }
    }
    if (message.coverLetterArtifactId) {
      const ok = await uploadArtifactToFileInput(message.coverLetterArtifactId as number, "cover_letter");
      if (ok) {
        result.filled++;
        result.fields.push("cover_letter_file");
      }
    }

    sendResponse({ ok: true, filled: result.filled, fields: result.fields });
  })();

  return true; // keep channel open
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
