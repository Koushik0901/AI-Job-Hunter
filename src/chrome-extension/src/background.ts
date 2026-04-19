/**
 * Service worker for AI Job Hunter Autofill.
 * - Auto-opens the side panel when navigating to supported ATS application pages.
 * - Relays AUTOFILL_PAGE (from popup) and SIDEPANEL_AUTOFILL (from side panel) to the content script.
 */

const ATS_URL_PATTERNS: RegExp[] = [
  /boards\.greenhouse\.io\/.+\/jobs\//,
  /job-boards\.greenhouse\.io\/.+\/jobs\//,
  /jobs\.lever\.co\/.+\/.+/,
  /jobs\.ashbyhq\.com\/.+\/.+/,
  /apply\.workable\.com\/.+\/j\//,
  /jobs\.smartrecruiters\.com\//,
  /smartrecruiters\.com\/.+\/jobs\//,
];

// Auto-open side panel when user navigates to a supported ATS page
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url) {
    const isAts = ATS_URL_PATTERNS.some((p) => p.test(tab.url!));
    if (isAts) {
      chrome.sidePanel.open({ tabId }).catch(() => {
        // Silently ignore — side panel open requires user gesture in some Chrome versions
      });
    }
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const isAutofill =
    message.type === "AUTOFILL_PAGE" || message.type === "SIDEPANEL_AUTOFILL";
  if (!isAutofill) return;

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab?.id) {
      sendResponse({ ok: false, error: "No active tab" });
      return;
    }
    chrome.tabs.sendMessage(
      tab.id,
      {
        type: "DO_AUTOFILL",
        resumeArtifactId: message.resumeArtifactId ?? null,
        coverLetterArtifactId: message.coverLetterArtifactId ?? null,
      },
      (response) => {
        if (chrome.runtime.lastError) {
          sendResponse({ ok: false, error: chrome.runtime.lastError.message });
        } else {
          sendResponse(response);
        }
      }
    );
  });
  return true; // keep channel open for async response
});
