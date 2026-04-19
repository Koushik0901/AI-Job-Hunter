import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { AutofillProfile } from "../api";
import { checkHealth, clearProfileCache, fetchAutofillProfile, getDashboardUrl, setDashboardUrl } from "../api";
import "./popup.css";

type Status = "checking" | "connected" | "disconnected";

interface FillResult {
  ok: boolean;
  filled?: number;
  fields?: string[];
  error?: string;
}

const PROFILE_FIELDS: { key: keyof AutofillProfile; label: string }[] = [
  { key: "first_name",    label: "First Name"  },
  { key: "last_name",     label: "Last Name"   },
  { key: "email",         label: "Email"        },
  { key: "phone",         label: "Phone"        },
  { key: "linkedin_url",  label: "LinkedIn"     },
  { key: "city",          label: "Location"     },
];

function getInitials(profile: AutofillProfile): string {
  const name = [profile.first_name, profile.last_name].filter(Boolean).join(" ") || profile.full_name || "";
  return name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase() || "AJ";
}

function getDisplayName(profile: AutofillProfile): string {
  return [profile.first_name, profile.last_name].filter(Boolean).join(" ") || profile.full_name || "Your Profile";
}

/* ── Settings gear icon ─────────────────────────────────────── */
function GearIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

/* ── Profile card ───────────────────────────────────────────── */
function ProfileCard({ profile }: { profile: AutofillProfile }) {
  const readyCount = PROFILE_FIELDS.filter((f) => profile[f.key]).length;
  return (
    <div className="profile-card">
      <div className="profile-avatar">{getInitials(profile)}</div>
      <div className="profile-info">
        <div className="profile-name">{getDisplayName(profile)}</div>
        {profile.email && <div className="profile-email">{profile.email}</div>}
      </div>
      <div className="profile-counter">{readyCount}/{PROFILE_FIELDS.length}</div>
    </div>
  );
}

/* ── Field readiness grid ───────────────────────────────────── */
function FieldGrid({ profile }: { profile: AutofillProfile }) {
  return (
    <div>
      <div className="field-section-title">Ready to fill</div>
      <div className="field-grid">
        {PROFILE_FIELDS.map((f) => {
          const has = Boolean(profile[f.key]);
          return (
            <div key={f.key} className={`field-chip ${has ? "field-chip--ready" : "field-chip--missing"}`}>
              {has
                ? <span className="field-chip-check">✓</span>
                : <span className="field-chip-dash">—</span>}
              <span>{f.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main popup ─────────────────────────────────────────────── */
function Popup() {
  const [status, setStatus]           = useState<Status>("checking");
  const [filling, setFilling]         = useState(false);
  const [fillResult, setFillResult]   = useState<FillResult | null>(null);
  const [profile, setProfile]         = useState<AutofillProfile | null>(null);
  const [dashUrl, setDashUrl]         = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [draftUrl, setDraftUrl]       = useState("");

  const refresh = useCallback(async () => {
    setStatus("checking");
    const ok = await checkHealth();
    setStatus(ok ? "connected" : "disconnected");
    if (ok) {
      const p = await fetchAutofillProfile();
      setProfile(p);
    } else {
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    getDashboardUrl().then((url) => { setDashUrl(url); setDraftUrl(url); });
    refresh();
  }, [refresh]);

  function handleAutofill() {
    setFilling(true);
    setFillResult(null);
    chrome.runtime.sendMessage({ type: "AUTOFILL_PAGE" }, (response) => {
      setFilling(false);
      if (!response) {
        setFillResult({ ok: false, error: "No response. Make sure you are on a supported application page." });
        return;
      }
      setFillResult(response as FillResult);
    });
  }

  async function handleSaveUrl() {
    await setDashboardUrl(draftUrl.trim());
    setDashUrl(draftUrl.trim());
    clearProfileCache();
    setShowSettings(false);
    refresh();
  }

  const statusLabel = status === "connected" ? "Connected" : status === "disconnected" ? "Offline" : "…";

  return (
    <div className="popup-root">

      {/* ── Header ── */}
      <div className="popup-header">
        <div className="popup-header-brand">
          <div className="popup-logo">AJH</div>
          <div>
            <div className="popup-brand-name">AI Job Hunter</div>
            <div className="popup-brand-sub">Autofill</div>
          </div>
        </div>
        <div className="popup-header-right">
          <div className={`status-badge status-badge--${status}`}>
            <span className="status-dot" />
            {statusLabel}
          </div>
          <button
            className={`icon-btn${showSettings ? " icon-btn--active" : ""}`}
            onClick={() => setShowSettings((s) => !s)}
            title="Settings"
          >
            <GearIcon />
          </button>
        </div>
      </div>

      {/* ── Settings panel ── */}
      {showSettings && (
        <div className="settings-panel">
          <div className="settings-label">Dashboard URL</div>
          <input
            className="settings-input"
            value={draftUrl}
            onChange={(e) => setDraftUrl(e.target.value)}
            placeholder="http://127.0.0.1:8000"
          />
          <div className="settings-actions">
            <button className="btn btn--primary" onClick={handleSaveUrl}>Save</button>
            <button className="btn btn--ghost" onClick={() => { setShowSettings(false); setDraftUrl(dashUrl); }}>Cancel</button>
          </div>
        </div>
      )}

      {/* ── Body ── */}
      <div className="popup-body">

        {/* Profile + fields */}
        {status === "checking" && (
          <div className="checking-dots">
            <span /><span /><span />
          </div>
        )}

        {status === "connected" && !profile && (
          <div className="empty-state">
            <div className="empty-state-icon">👤</div>
            <div className="empty-state-title">No profile found</div>
            <div className="empty-state-sub">Add your details in the AI Job Hunter dashboard to enable autofill.</div>
            <a 
              href={dashUrl ? `${dashUrl}/settings` : "#"} 
              target="_blank" 
              rel="noreferrer" 
              className="btn btn--primary"
              style={{ marginTop: 12, textDecoration: "none", display: "inline-block" }}
            >
              Setup Profile
            </a>
          </div>
        )}

        {status === "disconnected" && (
          <div className="empty-state">
            <div className="empty-state-icon">🔌</div>
            <div className="empty-state-title">Backend not running</div>
            <div className="empty-state-sub">Start the AI Job Hunter server at<br />{dashUrl}</div>
          </div>
        )}

        {profile && (
          <>
            <ProfileCard profile={profile} />
            <FieldGrid profile={profile} />
            {PROFILE_FIELDS.filter((f) => !profile[f.key]).length > 0 && (
              <div style={{ marginTop: 12, textAlign: "center" }}>
                <a 
                  href={`${dashUrl}/settings`} 
                  target="_blank" 
                  rel="noreferrer" 
                  style={{ fontSize: 11, color: "var(--accent)", textDecoration: "none" }}
                >
                  Complete your profile in Settings →
                </a>
              </div>
            )}
          </>
        )}

        {/* Fill result */}
        {fillResult && (
          <div className={`fill-result ${fillResult.ok ? "fill-result--ok" : "fill-result--err"}`}>
            <span className="fill-result-icon">{fillResult.ok ? "✓" : "!"}</span>
            <span>
              {fillResult.ok
                ? `Filled ${fillResult.filled} field${fillResult.filled === 1 ? "" : "s"}: ${fillResult.fields?.join(", ") || "none"}`
                : fillResult.error}
            </span>
          </div>
        )}

        {/* CTA */}
        <button
          className="btn-autofill"
          disabled={filling || status !== "connected"}
          onClick={handleAutofill}
        >
          {filling ? (
            <><span className="btn-spinner" /> Filling…</>
          ) : (
            <><span className="btn-lightning">⚡</span> Autofill This Page</>
          )}
        </button>

      </div>

      {/* ── Footer ── */}
      <div className="popup-footer">
        Greenhouse · Lever · Ashby · Workable
      </div>

    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<Popup />);
