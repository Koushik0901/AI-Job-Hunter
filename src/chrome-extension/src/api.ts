/**
 * Dashboard API client for the Chrome extension.
 * The base URL is configurable via chrome.storage.sync (key: "dashboardUrl").
 */

export interface AutofillProfile {
  // Name
  first_name: string | null;
  last_name: string | null;
  full_name: string | null;
  pronouns: string | null;
  // Contact
  email: string | null;
  phone: string | null;
  // Address
  street_address: string | null;
  address_line2: string | null;
  city: string | null;
  state_province: string | null;
  postal_code: string | null;
  country: string | null;
  // Links
  linkedin_url: string | null;
  portfolio_url: string | null;
  github_url: string | null;
  // Career
  years_experience: number | null;
  degree: string | null;
  degree_field: string | null;
  desired_salary: string | null;
  work_authorization: string | null;
  requires_visa_sponsorship: boolean;
  willing_to_relocate: boolean;
}

const DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8000";

export async function getDashboardUrl(): Promise<string> {
  return new Promise((resolve) => {
    chrome.storage.sync.get("dashboardUrl", (result) => {
      resolve((result.dashboardUrl as string | undefined) || DEFAULT_DASHBOARD_URL);
    });
  });
}

export async function setDashboardUrl(url: string): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.sync.set({ dashboardUrl: url }, resolve);
  });
}

export async function checkHealth(): Promise<boolean> {
  const base = await getDashboardUrl();
  try {
    const resp = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(3000) });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function fetchAutofillProfile(): Promise<AutofillProfile | null> {
  const base = await getDashboardUrl();
  try {
    const resp = await fetch(`${base}/api/profile/autofill-export`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return null;
    return (await resp.json()) as AutofillProfile;
  } catch {
    return null;
  }
}

/** Cache profile in session storage for up to 5 minutes. */
export async function getCachedProfile(): Promise<AutofillProfile | null> {
  const KEY = "ajh_autofill_profile";
  const TTL_KEY = "ajh_autofill_profile_ts";
  const TTL_MS = 5 * 60 * 1000;

  return new Promise((resolve) => {
    chrome.storage.session.get([KEY, TTL_KEY], async (result) => {
      const ts = result[TTL_KEY] as number | undefined;
      const cached = result[KEY] as AutofillProfile | undefined;
      if (cached && ts && Date.now() - ts < TTL_MS) {
        resolve(cached);
        return;
      }
      const fresh = await fetchAutofillProfile();
      if (fresh) {
        chrome.storage.session.set({ [KEY]: fresh, [TTL_KEY]: Date.now() });
      }
      resolve(fresh);
    });
  });
}

export function clearProfileCache(): void {
  chrome.storage.session.remove(["ajh_autofill_profile", "ajh_autofill_profile_ts"]);
}

export interface ArtifactInfo {
  id: number;
  artifact_type: "resume" | "cover_letter";
  content_md: string;
  updated_at: string;
}

export interface ArtifactsByUrlResponse {
  job_info: { title: string; company: string; location: string | null; job_id: string } | null;
  resume: ArtifactInfo | null;
  cover_letter: ArtifactInfo | null;
}

// ---------------------------------------------------------------------------
// Autofill corrections (edit learning) — stored in chrome.storage.local
// ---------------------------------------------------------------------------

const CORRECTIONS_KEY = "autofill_corrections";
type AllCorrections = Record<string, Record<string, string>>; // {[ats_host]: {[field_key]: value}}

export async function getCorrections(atsHost: string): Promise<Record<string, string>> {
  return new Promise((resolve) => {
    chrome.storage.local.get(CORRECTIONS_KEY, (result) => {
      const all = (result[CORRECTIONS_KEY] as AllCorrections) || {};
      resolve(all[atsHost] || {});
    });
  });
}

export async function saveCorrections(
  atsHost: string,
  corrections: Record<string, string>,
): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(CORRECTIONS_KEY, (result) => {
      const all = (result[CORRECTIONS_KEY] as AllCorrections) || {};
      all[atsHost] = { ...(all[atsHost] || {}), ...corrections };
      chrome.storage.local.set({ [CORRECTIONS_KEY]: all }, resolve);
    });
  });
}

export async function getArtifactsByUrl(url: string): Promise<ArtifactsByUrlResponse | null> {
  const base = await getDashboardUrl();
  try {
    const resp = await fetch(
      `${base}/api/artifacts/by-url?url=${encodeURIComponent(url)}`,
      { signal: AbortSignal.timeout(5000) }
    );
    if (!resp.ok) return null;
    return (await resp.json()) as ArtifactsByUrlResponse;
  } catch {
    return null;
  }
}
