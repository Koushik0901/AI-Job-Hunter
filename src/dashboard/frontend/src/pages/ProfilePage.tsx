import { useEffect, useMemo, useState } from "react";
import { getProfile, putProfile } from "../api";
import { ThemedLoader } from "../components/ThemedLoader";
import type { CandidateProfile } from "../types";

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

const EMPTY_PROFILE: CandidateProfile = {
  years_experience: 0,
  skills: [],
  target_role_families: [],
  requires_visa_sponsorship: false,
  education: [],
  degree: null,
  degree_field: null,
  updated_at: null,
};

function normalizeTags(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const raw of values) {
    const cleaned = raw.trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function normalizeEducation(values: CandidateProfile["education"]): CandidateProfile["education"] {
  const seen = new Set<string>();
  const output: CandidateProfile["education"] = [];
  for (const raw of values) {
    const degree = (raw.degree ?? "").trim();
    const field = (raw.field ?? "").trim() || null;
    if (!degree) continue;
    const key = `${degree.toLowerCase()}::${(field ?? "").toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push({ degree, field });
  }
  return output;
}

function profileFingerprint(profile: CandidateProfile): string {
  const comparable = {
    years_experience: Math.max(0, Number(profile.years_experience || 0)),
    requires_visa_sponsorship: Boolean(profile.requires_visa_sponsorship),
    education: normalizeEducation(profile.education ?? []),
    degree: (profile.degree ?? "").trim(),
    degree_field: (profile.degree_field ?? "").trim(),
    skills: normalizeTags(profile.skills),
    target_role_families: normalizeTags(profile.target_role_families),
  };
  return JSON.stringify(comparable);
}

function pushToken(setter: (updater: (current: string[]) => string[]) => void, token: string): void {
  const parsed = token
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (parsed.length === 0) return;

  setter((current) => normalizeTags([...current, ...parsed]));
}

export function ProfilePage() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  const [original, setOriginal] = useState<CandidateProfile>(EMPTY_PROFILE);
  const [draft, setDraft] = useState<CandidateProfile>(EMPTY_PROFILE);
  const [skillsInput, setSkillsInput] = useState("");
  const [familiesInput, setFamiliesInput] = useState("");
  const [educationDegreeInput, setEducationDegreeInput] = useState("");
  const [educationFieldInput, setEducationFieldInput] = useState("");

  const isDirty = useMemo(() => profileFingerprint(draft) !== profileFingerprint(original), [draft, original]);

  useEffect(() => {
    if (saveState !== "saving") {
      setSaveState(isDirty ? "dirty" : "idle");
    }
  }, [isDirty, saveState]);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile(): Promise<void> {
      setLoading(true);
      setLoadError(null);
      try {
        const profile = await getProfile();
        if (cancelled) return;
        setOriginal(profile);
        setDraft(profile);
      } catch (error) {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load profile");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  async function saveProfile(): Promise<void> {
    setSaveError(null);
    setSaveState("saving");

    const payload: CandidateProfile = {
      ...draft,
      years_experience: Math.max(0, Math.min(60, Number(draft.years_experience || 0))),
      education: normalizeEducation(draft.education ?? []),
      degree: normalizeEducation(draft.education ?? [])[0]?.degree ?? null,
      degree_field: normalizeEducation(draft.education ?? [])[0]?.field ?? null,
      skills: normalizeTags(draft.skills),
      target_role_families: normalizeTags(draft.target_role_families),
      updated_at: draft.updated_at,
    };

    try {
      const saved = await putProfile(payload);
      setOriginal(saved);
      setDraft(saved);
      setSkillsInput("");
      setFamiliesInput("");
      setEducationDegreeInput("");
      setEducationFieldInput("");
      setSaveState("saved");
      window.setTimeout(() => {
        setSaveState("idle");
      }, 1400);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "Failed to save profile");
      setSaveState("error");
    }
  }

  function saveLabel(): string {
    switch (saveState) {
      case "saving":
        return "Saving...";
      case "saved":
        return "Saved";
      case "error":
        return "Retry Save";
      default:
        return "Save Profile";
    }
  }

  if (loading) {
    return (
      <div className="page-loader-shell">
        <ThemedLoader label="Loading profile" />
      </div>
    );
  }

  function addEducation(): void {
    const degree = educationDegreeInput.trim();
    const field = educationFieldInput.trim() || null;
    if (!degree) return;
    setDraft((current) => ({
      ...current,
      education: normalizeEducation([...(current.education ?? []), { degree, field }]),
    }));
    setEducationDegreeInput("");
    setEducationFieldInput("");
  }

  return (
    <div className="profile-page">
      <section className="profile-hero">
        <div>
          <p className="page-kicker">Candidate Configuration</p>
          <h2>Scoring Profile</h2>
          <p className="profile-hero-copy">
            Keep this profile up to date so match ranking reflects your real background and goals.
          </p>
        </div>
        <div className="profile-hero-actions">
          <span className={`save-badge ${saveState}`}>{saveState === "dirty" ? "Unsaved changes" : saveState === "saved" ? "All changes saved" : saveState === "saving" ? "Saving" : "Ready"}</span>
          <button
            type="button"
            className="primary-btn"
            disabled={!isDirty || saveState === "saving"}
            onClick={() => void saveProfile()}
          >
            {saveLabel()}
          </button>
        </div>
      </section>

      {loadError && <div className="error-banner">{loadError}</div>}
      {saveError && <div className="error-banner">{saveError}</div>}

      <section className="profile-grid">
        <section className="profile-card">
          <h3>Core Inputs</h3>
          <div className="profile-form-grid">
            <label>
              <span>Years Experience</span>
              <input
                type="number"
                min={0}
                max={60}
                value={draft.years_experience}
                onChange={(event) => setDraft((current) => ({ ...current, years_experience: Number(event.target.value || 0) }))}
              />
            </label>
          </div>
        </section>

        <section className="profile-card">
          <h3>Education</h3>
          <div className="token-editor">
            <div className="token-list" role="list" aria-label="Education list">
              {(draft.education ?? []).map((entry, index) => (
                <span className="token-chip" role="listitem" key={`${entry.degree}-${entry.field ?? "none"}-${index}`}>
                  {entry.degree}{entry.field ? ` (${entry.field})` : ""}
                  <button
                    type="button"
                    aria-label={`Remove ${entry.degree}`}
                    onClick={() => {
                      setDraft((current) => ({
                        ...current,
                        education: current.education.filter((_, itemIndex) => itemIndex !== index),
                      }));
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div className="profile-form-grid">
              <label>
                <span>Degree</span>
                <input
                  type="text"
                  value={educationDegreeInput}
                  onChange={(event) => setEducationDegreeInput(event.target.value)}
                />
              </label>
              <label>
                <span>Field</span>
                <input
                  type="text"
                  value={educationFieldInput}
                  onChange={(event) => setEducationFieldInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addEducation();
                    }
                  }}
                />
              </label>
            </div>
            <button type="button" className="ghost-btn" onClick={addEducation}>
              Add Education
            </button>
          </div>
        </section>

        <section className="profile-card">
          <h3>Target Role Families</h3>
          <div className="token-editor">
            <div className="token-list" role="list" aria-label="Target role families">
              {draft.target_role_families.map((family) => (
                <span className="token-chip" role="listitem" key={family}>
                  {family}
                  <button
                    type="button"
                    aria-label={`Remove ${family}`}
                    onClick={() => {
                      setDraft((current) => ({
                        ...current,
                        target_role_families: current.target_role_families.filter((item) => item !== family),
                      }));
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <input
              type="text"
              value={familiesInput}
              onChange={(event) => setFamiliesInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === ",") {
                  event.preventDefault();
                  pushToken((updater) => {
                    setDraft((current) => ({ ...current, target_role_families: updater(current.target_role_families) }));
                  }, familiesInput);
                  setFamiliesInput("");
                }
              }}
              onBlur={() => {
                pushToken((updater) => {
                  setDraft((current) => ({ ...current, target_role_families: updater(current.target_role_families) }));
                }, familiesInput);
                setFamiliesInput("");
              }}
            />
          </div>
        </section>

        <section className="profile-card profile-card-wide">
          <h3>Skill Inventory</h3>
          <div className="token-editor">
            <div className="token-list" role="list" aria-label="Skills list">
              {draft.skills.map((skill) => (
                <span className="token-chip token-chip-accent" role="listitem" key={skill}>
                  {skill}
                  <button
                    type="button"
                    aria-label={`Remove ${skill}`}
                    onClick={() => {
                      setDraft((current) => ({
                        ...current,
                        skills: current.skills.filter((item) => item !== skill),
                      }));
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <input
              type="text"
              value={skillsInput}
              onChange={(event) => setSkillsInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === ",") {
                  event.preventDefault();
                  pushToken((updater) => {
                    setDraft((current) => ({ ...current, skills: updater(current.skills) }));
                  }, skillsInput);
                  setSkillsInput("");
                }
              }}
              onBlur={() => {
                pushToken((updater) => {
                  setDraft((current) => ({ ...current, skills: updater(current.skills) }));
                }, skillsInput);
                setSkillsInput("");
              }}
            />
          </div>
        </section>
      </section>

      <section className="profile-summary profile-card">
        <h3>Live Summary</h3>
        <p>
          <strong>{draft.years_experience}</strong> years experience,
          education entries: <strong>{draft.education.length}</strong>,
          <strong> {draft.skills.length}</strong> skills,
          <strong> {draft.target_role_families.length}</strong> role families.
        </p>
        <p className="board-note">Last updated: {draft.updated_at ?? "-"}</p>
      </section>
    </div>
  );
}
