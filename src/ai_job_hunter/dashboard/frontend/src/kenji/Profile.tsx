// Kenji — Profile screen. All ATS-ready fields + documents + career intent.
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties, KeyboardEvent } from "react";
import { api, type BaseDocument, type CandidateProfile, type EducationEntry } from "../api";
import { useData } from "../DataContext";
import { Icon } from "./ui";

// ─── helpers ────────────────────────────────────────────────────────────────

function initialsOf(name: string | null | undefined): string {
  if (!name) return "··";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map(p => p[0]?.toUpperCase() || "").join("") || "··";
}

type CompletenessCheck = { label: string; ok: boolean; section: string };

function completenessChecks(p: CandidateProfile): CompletenessCheck[] {
  return [
    { label: "First & last name",      ok: !!(p.first_name?.trim() || p.full_name?.trim()), section: "Identity" },
    { label: "Email address",          ok: !!p.email?.trim(),                                section: "Contact" },
    { label: "Phone number",           ok: !!p.phone?.trim(),                                section: "Contact" },
    { label: "City & country",         ok: !!(p.city?.trim() && p.country?.trim()),          section: "Address" },
    { label: "LinkedIn URL",           ok: !!p.linkedin_url?.trim(),                        section: "Links" },
    { label: "Years of experience",    ok: p.years_experience > 0,                          section: "Career" },
    { label: "Desired job titles",     ok: p.desired_job_titles.length > 0,                 section: "Career" },
    { label: "At least 5 skills",      ok: p.skills.length >= 5,                            section: "Skills" },
    { label: "Career narrative",       ok: !!p.narrative_intent?.trim(),                    section: "Career" },
    { label: "Work authorization",     ok: !!p.work_authorization?.trim(),                  section: "Career" },
    { label: "Education entry",        ok: p.education.length > 0 || !!p.degree,            section: "Education" },
    { label: "Salary expectation",     ok: !!p.desired_salary?.trim(),                      section: "Career" },
  ];
}

function docTypeLabel(t: string) {
  if (t === "resume") return "Resume";
  if (t === "cover_letter") return "Cover letter";
  return t.replace(/_/g, " ");
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const d = Math.floor(ms / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

// ─── tiny primitives ────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mono" style={{
      fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase",
      color: "var(--outline)", fontWeight: 600, marginBottom: 14,
    }}>
      {children}
    </div>
  );
}

function FL({ children }: { children: React.ReactNode }) {
  return <label className="field-label">{children}</label>;
}

function FG({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div className="field-group" style={style}>{children}</div>;
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" className={"toggle-track" + (on ? " on" : "")}
      onClick={() => onChange(!on)} aria-checked={on} role="switch">
      <div className="toggle-thumb"/>
    </button>
  );
}

function CompletenessRing({ score }: { score: number }) {
  const size = 60, stroke = 5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c - (score / 100) * c;
  const color = score >= 80 ? "var(--primary)" : score >= 50 ? "var(--warn)" : "var(--error)";
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} stroke="var(--sc-high)" strokeWidth={stroke} fill="none"/>
        <circle cx={size/2} cy={size/2} r={r} stroke={color} strokeWidth={stroke}
          strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round" fill="none"
          style={{ transition: "stroke-dashoffset 500ms ease" }}/>
      </svg>
      <div style={{
        position: "absolute", inset: 0, display: "grid", placeItems: "center",
        fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14,
        color: "var(--on-surface)", letterSpacing: "-0.02em",
      }}>
        {score}%
      </div>
    </div>
  );
}

// ─── chip tag input ──────────────────────────────────────────────────────────

function ChipTagInput({
  values, onChange, placeholder, mono = false,
}: {
  values: string[]; onChange: (v: string[]) => void; placeholder?: string; mono?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [removing, setRemoving] = useState<Set<string>>(new Set());

  const commit = () => {
    const v = draft.trim();
    if (v && !values.map(x => x.toLowerCase()).includes(v.toLowerCase())) {
      onChange([...values, v]);
    }
    setDraft("");
  };

  const removeChip = (val: string) => {
    setRemoving(prev => new Set([...prev, val]));
    setTimeout(() => {
      onChange(values.filter(v => v !== val));
      setRemoving(prev => { const n = new Set(prev); n.delete(val); return n; });
    }, 160);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); }
    if (e.key === "Backspace" && !draft && values.length) removeChip(values[values.length - 1]);
  };

  return (
    <div className="row gap-6" style={{
      flexWrap: "wrap", minHeight: 42, padding: "8px 10px",
      border: "1px solid var(--outline-variant)", borderRadius: "var(--r)",
      background: "var(--sc-lowest)",
      transition: "border-color 140ms",
    }}
      onClick={e => (e.currentTarget.querySelector("input") as HTMLInputElement)?.focus()}
    >
      {values.map((v) => (
        <span key={v} className={"chip" + (mono ? " mono" : "") + (removing.has(v) ? " removing" : "")}
          style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {v}
          <button type="button" onClick={ev => { ev.stopPropagation(); removeChip(v); }}
            style={{ background: "none", border: 0, padding: 0, cursor: "pointer", color: "inherit", lineHeight: 1, display: "flex" }}>
            <Icon name="x" size={10}/>
          </button>
        </span>
      ))}
      <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={onKey} onBlur={commit}
        placeholder={values.length === 0 ? placeholder : ""}
        style={{
          border: 0, outline: 0, background: "transparent", flex: 1, minWidth: 80,
          fontSize: mono ? 12 : 13.5, fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          color: "var(--on-surface)",
        }}
      />
    </div>
  );
}

// ─── document row ────────────────────────────────────────────────────────────

function DocRow({ doc, onDelete, onSetDefault }: {
  doc: BaseDocument; onDelete: () => void; onSetDefault: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <div className="doc-row">
      <Icon name="doc" size={14} style={{ color: "var(--outline)", flexShrink: 0 } as CSSProperties}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {doc.filename}
        </div>
        <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 2 }}>
          {docTypeLabel(doc.doc_type)} · {timeAgo(doc.created_at)}
        </div>
      </div>
      {doc.is_default && <span className="chip primary mono" style={{ fontSize: 9.5, padding: "2px 7px" }}>default</span>}
      {!doc.is_default && !confirmDelete && (
        <button className="btn ghost sm" style={{ fontSize: 11.5, padding: "4px 9px" }} onClick={onSetDefault}>
          Set default
        </button>
      )}
      {confirmDelete ? (
        <div className="row gap-6">
          <span className="mono" style={{ fontSize: 11, color: "var(--error)" }}>delete?</span>
          <button className="btn ghost sm" style={{ padding: "4px 8px", color: "var(--error)" }}
            onClick={async () => {
              setDeleting(true);
              try { await onDelete(); } finally { setDeleting(false); setConfirmDelete(false); }
            }} disabled={deleting}>
            Yes
          </button>
          <button className="btn ghost sm" style={{ padding: "4px 8px" }}
            onClick={() => setConfirmDelete(false)} disabled={deleting}>
            Cancel
          </button>
        </div>
      ) : (
        <button className="btn ghost sm" style={{ padding: "4px 8px", color: "var(--error)" }}
          onClick={() => setConfirmDelete(true)} disabled={deleting}>
          <Icon name="x" size={12}/>
        </button>
      )}
    </div>
  );
}

// ─── education entry ─────────────────────────────────────────────────────────

function EducationRow({ entry, onChange, onRemove }: {
  entry: EducationEntry; onChange: (e: EducationEntry) => void; onRemove: () => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "center" }}>
      <input className="field-input" value={entry.degree}
        onChange={e => onChange({ ...entry, degree: e.target.value })}
        placeholder="Degree (e.g. B.Sc.)"/>
      <input className="field-input" value={entry.field ?? ""}
        onChange={e => onChange({ ...entry, field: e.target.value || null })}
        placeholder="Field (e.g. Computer Science)"/>
      <button className="btn ghost sm" style={{ padding: "6px 8px", color: "var(--error)" }} onClick={onRemove}>
        <Icon name="x" size={13}/>
      </button>
    </div>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

type SaveState = "idle" | "saving" | "saved" | "error";

const EMPTY_PROFILE: CandidateProfile = {
  years_experience: 0,
  skills: [],
  desired_job_titles: [],
  target_role_families: [],
  requires_visa_sponsorship: false,
  willing_to_relocate: false,
  education: [],
  degree: null,
  degree_field: null,
  score_version: null,
  updated_at: null,
  full_name: null,
  first_name: null,
  last_name: null,
  pronouns: null,
  email: null,
  phone: null,
  street_address: null,
  address_line2: null,
  city: null,
  state_province: null,
  postal_code: null,
  country: null,
  linkedin_url: null,
  portfolio_url: null,
  github_url: null,
  narrative_intent: null,
  desired_salary: null,
  work_authorization: null,
  preferred_work_mode: null,
};

export function Profile() {
  const { profile: ctxProfile, refreshAll } = useData();

  const [form, setForm] = useState<CandidateProfile>(ctxProfile ?? EMPTY_PROFILE);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [docs, setDocs] = useState<BaseDocument[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadDocType, setUploadDocType] = useState<"resume" | "cover_letter">("resume");

  const fileRef = useRef<HTMLInputElement>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (ctxProfile) setForm(prev => dirty ? prev : { ...EMPTY_PROFILE, ...ctxProfile });
  }, [ctxProfile]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    try { setDocs(await api.listBaseDocs()); }
    catch { /* silent */ }
    finally { setDocsLoading(false); }
  }, []);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  const patch = (updates: Partial<CandidateProfile>) => {
    setForm(f => ({ ...f, ...updates }));
    setDirty(true);
  };

  const save = async () => {
    setSaveState("saving");
    setSaveError(null);

    // Strip empty education entries — Pydantic requires degree min_length=1
    const payload: CandidateProfile = {
      ...form,
      education: form.education.filter(e => e.degree.trim().length > 0),
    };

    // Optimistic: mark clean immediately so UI feels instant
    setDirty(false);

    try {
      const updated = await api.updateProfile(payload);
      setForm({ ...EMPTY_PROFILE, ...updated });
      setSaveState("saved");
      refreshAll().catch(() => {/* best-effort */});
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaveState("idle"), 2400);
    } catch (e: unknown) {
      // Optimistic rollback — re-dirty so user can retry
      setDirty(true);
      const msg = e instanceof Error ? e.message : "Unknown error";
      setSaveError(msg);
      setSaveState("error");
    }
  };

  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try { await api.uploadDocument(file, uploadDocType); await loadDocs(); }
    catch { /* silent */ }
    finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const checks = completenessChecks(form);
  const missing = checks.filter(c => !c.ok);
  const score = Math.round(((checks.length - missing.length) / checks.length) * 100);

  const displayName = [form.first_name, form.last_name].filter(Boolean).join(" ") || form.full_name || "You";

  return (
    <div className="content" style={{ maxWidth: 1100, paddingBottom: 80 }}>

      {/* ── page header ── */}
      <div style={{ marginBottom: 36 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--outline)", marginBottom: 10 }}>profile</div>
        <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 32, letterSpacing: "-0.025em", color: "var(--on-surface)", lineHeight: 1.1 }}>
          Who you are<span style={{ fontStyle: "italic", fontWeight: 500, color: "var(--primary)" }}> on every application.</span>
        </div>
        <div style={{ marginTop: 10, fontSize: 13.5, color: "var(--outline)", maxWidth: 560 }}>
          Kenji autofills Greenhouse, Ashby, and Lever forms with this data. Keep it complete and current.
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 28, alignItems: "start" }}>

        {/* ── LEFT ── */}
        <div className="col" style={{ gap: 24 }}>

          {/* Identity */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Identity</SectionLabel>
            <div className="col" style={{ gap: 16 }}>
              <div className="field-row two">
                <FG>
                  <FL>First name</FL>
                  <input className="field-input" value={form.first_name ?? ""}
                    onChange={e => patch({ first_name: e.target.value || null })}
                    placeholder="Jane"/>
                </FG>
                <FG>
                  <FL>Last name</FL>
                  <input className="field-input" value={form.last_name ?? ""}
                    onChange={e => patch({ last_name: e.target.value || null })}
                    placeholder="Doe"/>
                </FG>
              </div>
              <FG>
                <FL>Full legal name <span style={{ fontWeight: 400, color: "var(--outline)" }}>— as it appears on official docs</span></FL>
                <input className="field-input" value={form.full_name ?? ""}
                  onChange={e => patch({ full_name: e.target.value || null })}
                  placeholder="Jane Doe"/>
              </FG>
              <FG style={{ maxWidth: 220 }}>
                <FL>Pronouns <span style={{ fontWeight: 400, color: "var(--outline)" }}>— optional</span></FL>
                <input className="field-input" value={form.pronouns ?? ""}
                  onChange={e => patch({ pronouns: e.target.value || null })}
                  placeholder="she/her"/>
              </FG>
            </div>
          </div>

          {/* Contact */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Contact</SectionLabel>
            <div className="col" style={{ gap: 16 }}>
              <div className="field-row two">
                <FG>
                  <FL>Email</FL>
                  <input className="field-input" type="email" value={form.email ?? ""}
                    onChange={e => patch({ email: e.target.value || null })}
                    placeholder="jane@example.com"/>
                </FG>
                <FG>
                  <FL>Phone</FL>
                  <input className="field-input" type="tel" value={form.phone ?? ""}
                    onChange={e => patch({ phone: e.target.value || null })}
                    placeholder="+1 (555) 000-0000"/>
                </FG>
              </div>
            </div>
          </div>

          {/* Address */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Address</SectionLabel>
            <div className="col" style={{ gap: 16 }}>
              <FG>
                <FL>Street address</FL>
                <input className="field-input" value={form.street_address ?? ""}
                  onChange={e => patch({ street_address: e.target.value || null })}
                  placeholder="123 Main St"/>
              </FG>
              <FG>
                <FL>Apartment, suite, etc. <span style={{ fontWeight: 400, color: "var(--outline)" }}>— optional</span></FL>
                <input className="field-input" value={form.address_line2 ?? ""}
                  onChange={e => patch({ address_line2: e.target.value || null })}
                  placeholder="Apt 4B"/>
              </FG>
              <div className="field-row two">
                <FG>
                  <FL>City</FL>
                  <input className="field-input" value={form.city ?? ""}
                    onChange={e => patch({ city: e.target.value || null })}
                    placeholder="Edmonton"/>
                </FG>
                <FG>
                  <FL>Province / State</FL>
                  <input className="field-input" value={form.state_province ?? ""}
                    onChange={e => patch({ state_province: e.target.value || null })}
                    placeholder="Alberta"/>
                </FG>
              </div>
              <div className="field-row two">
                <FG>
                  <FL>Postal / ZIP code</FL>
                  <input className="field-input mono" value={form.postal_code ?? ""}
                    onChange={e => patch({ postal_code: e.target.value || null })}
                    placeholder="T5A 0A1"/>
                </FG>
                <FG>
                  <FL>Country</FL>
                  <input className="field-input" value={form.country ?? ""}
                    onChange={e => patch({ country: e.target.value || null })}
                    placeholder="Canada"/>
                </FG>
              </div>
            </div>
          </div>

          {/* Links */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Links</SectionLabel>
            <div className="col" style={{ gap: 16 }}>
              <FG>
                <FL>LinkedIn</FL>
                <input className="field-input mono" value={form.linkedin_url ?? ""}
                  onChange={e => patch({ linkedin_url: e.target.value || null })}
                  placeholder="https://linkedin.com/in/yourname"/>
              </FG>
              <div className="field-row two">
                <FG>
                  <FL>GitHub</FL>
                  <input className="field-input mono" value={form.github_url ?? ""}
                    onChange={e => patch({ github_url: e.target.value || null })}
                    placeholder="https://github.com/yourname"/>
                </FG>
                <FG>
                  <FL>Portfolio / website</FL>
                  <input className="field-input mono" value={form.portfolio_url ?? ""}
                    onChange={e => patch({ portfolio_url: e.target.value || null })}
                    placeholder="https://yoursite.com"/>
                </FG>
              </div>
            </div>
          </div>

          {/* Career intent */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Career intent</SectionLabel>
            <div className="col" style={{ gap: 16 }}>
              <div className="field-row two">
                <FG>
                  <FL>Years of experience</FL>
                  <div className="row gap-10" style={{ alignItems: "center" }}>
                    <input className="field-input" type="number" min={0} max={60}
                      value={form.years_experience}
                      onChange={e => patch({ years_experience: Math.max(0, Math.min(60, parseInt(e.target.value) || 0)) })}
                      style={{ maxWidth: 90 }}/>
                    <span style={{ fontSize: 13, color: "var(--outline)" }}>years</span>
                  </div>
                </FG>
                <FG>
                  <FL>Salary expectation</FL>
                  <input className="field-input" value={form.desired_salary ?? ""}
                    onChange={e => patch({ desired_salary: e.target.value || null })}
                    placeholder="120,000 – 160,000 CAD"/>
                </FG>
              </div>

              <FG>
                <FL>Work authorization</FL>
                <select className="field-input"
                  value={form.work_authorization ?? ""}
                  onChange={e => patch({ work_authorization: e.target.value || null })}>
                  <option value="">— select —</option>
                  <option value="citizen">Canadian / US Citizen</option>
                  <option value="permanent_resident">Permanent Resident (PR)</option>
                  <option value="work_permit">Open Work Permit</option>
                  <option value="student_permit">Post-grad / Study Permit</option>
                  <option value="require_sponsorship">Require Sponsorship</option>
                </select>
              </FG>

              <FG>
                <FL>Preferred work mode</FL>
                <div className="row gap-8" style={{ flexWrap: "wrap" }}>
                  {(["remote", "hybrid", "onsite"] as const).map(mode => (
                    <button key={mode} type="button"
                      className={"chip" + (form.preferred_work_mode === mode ? " primary" : "")}
                      style={{ cursor: "pointer", textTransform: "capitalize" }}
                      onClick={() => patch({ preferred_work_mode: form.preferred_work_mode === mode ? null : mode })}>
                      {mode}
                    </button>
                  ))}
                </div>
              </FG>

              <FG>
                <FL>Desired job titles <span style={{ fontWeight: 400, color: "var(--outline)" }}>— press Enter to add</span></FL>
                <ChipTagInput values={form.desired_job_titles}
                  onChange={v => patch({ desired_job_titles: v })}
                  placeholder="ML Engineer, Data Scientist…"/>
              </FG>

              <FG>
                <FL>Target role families <span style={{ fontWeight: 400, color: "var(--outline)" }}>— optional</span></FL>
                <ChipTagInput values={form.target_role_families}
                  onChange={v => patch({ target_role_families: v })}
                  placeholder="Applied ML, Research, MLOps…"/>
              </FG>

              <FG>
                <FL>Career narrative</FL>
                <textarea className="field-input"
                  value={form.narrative_intent ?? ""}
                  onChange={e => patch({ narrative_intent: e.target.value || null })}
                  placeholder="What are you looking for in your next role? What should employers know about you? Kenji uses this to write cover letters and sharpen match reasoning."
                  style={{ minHeight: 100 }}/>
              </FG>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div className="row gap-12" style={{ padding: "12px 14px", background: "var(--sc)", borderRadius: "var(--r)", border: "1px solid var(--outline-variant)" }}>
                  <Toggle on={form.requires_visa_sponsorship} onChange={v => patch({ requires_visa_sponsorship: v })}/>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)" }}>Requires visa sponsorship</div>
                    <div style={{ fontSize: 11.5, color: "var(--outline)", marginTop: 2 }}>Kenji flags roles that don't offer it</div>
                  </div>
                </div>
                <div className="row gap-12" style={{ padding: "12px 14px", background: "var(--sc)", borderRadius: "var(--r)", border: "1px solid var(--outline-variant)" }}>
                  <Toggle on={form.willing_to_relocate} onChange={v => patch({ willing_to_relocate: v })}/>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--on-surface)" }}>Willing to relocate</div>
                    <div style={{ fontSize: 11.5, color: "var(--outline)", marginTop: 2 }}>Opens onsite roles outside your city</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Skills */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Skills</SectionLabel>
            <div style={{ marginBottom: 10, fontSize: 13, color: "var(--outline)" }}>
              {form.skills.length} skills · press Enter or comma to add · click × to remove
            </div>
            <ChipTagInput values={form.skills} onChange={v => patch({ skills: v })}
              placeholder="Python, PyTorch, SQL, dbt, Spark…" mono/>
          </div>

          {/* Education */}
          <div className="card" style={{ padding: "22px 26px" }}>
            <SectionLabel>Education</SectionLabel>
            <div className="col" style={{ gap: 10 }}>
              {form.education.map((entry, i) => (
                <EducationRow key={i} entry={entry}
                  onChange={updated => {
                    const next = [...form.education];
                    next[i] = updated;
                    patch({ education: next });
                  }}
                  onRemove={() => patch({ education: form.education.filter((_, j) => j !== i) })}/>
              ))}
              {form.education.length === 0 && (
                <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic", paddingBottom: 2 }}>No entries yet.</div>
              )}
              <button className="btn sm" style={{ alignSelf: "flex-start", marginTop: 4 }}
                onClick={() => patch({ education: [...form.education, { degree: "", field: null }] })}>
                <Icon name="plus" size={12}/>Add entry
              </button>
            </div>
          </div>

        </div>

        {/* ── RIGHT ── */}
        <div className="col" style={{ gap: 20, position: "sticky", top: 20 }}>

          {/* Profile health */}
          <div className="card" style={{ padding: "20px 22px" }}>
            <SectionLabel>Profile health</SectionLabel>
            <div className="row gap-14" style={{ marginBottom: 14 }}>
              <CompletenessRing score={score}/>
              <div>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em", color: "var(--on-surface)" }}>
                  {score}% complete
                </div>
                <div style={{ fontSize: 12, color: "var(--outline)", marginTop: 3 }}>
                  {missing.length === 0 ? "All fields filled" : `${missing.length} field${missing.length > 1 ? "s" : ""} to go`}
                </div>
              </div>
            </div>
            <div className="completeness-track" style={{ marginBottom: 12 }}>
              <div className="completeness-fill" style={{ width: `${score}%` }}/>
            </div>
            {missing.length > 0 && (
              <div className="col" style={{ gap: 4 }}>
                {missing.map(c => (
                  <div key={c.label} className="row gap-8" style={{ fontSize: 11.5, color: "var(--on-surface-variant)" }}>
                    <div style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--outline)", flexShrink: 0, marginTop: 5 }}/>
                    <span>{c.label}</span>
                    <span className="mono" style={{ fontSize: 9.5, color: "var(--outline)", marginLeft: "auto" }}>{c.section}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Save card */}
          <div className="card" style={{ padding: "18px 22px" }}>
            <div className="col" style={{ gap: 10 }}>
              <button className="btn primary" onClick={save}
                disabled={!dirty || saveState === "saving"}
                style={{
                  width: "100%", justifyContent: "center",
                  background: saveState === "error" ? "var(--error)" : undefined,
                  borderColor: saveState === "error" ? "var(--error)" : undefined,
                  opacity: !dirty && saveState === "idle" ? 0.5 : 1,
                  transition: "opacity 200ms",
                }}>
                {saveState === "saving" && <span className="spinner"/>}
                {saveState === "saved" && <Icon name="check" size={13}/>}
                {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : saveState === "error" ? "Retry" : "Save profile"}
              </button>
              {dirty && saveState === "idle" && (
                <button className="btn ghost sm" style={{ width: "100%", justifyContent: "center" }}
                  onClick={() => { setForm(ctxProfile ? { ...EMPTY_PROFILE, ...ctxProfile } : EMPTY_PROFILE); setDirty(false); }}>
                  Discard changes
                </button>
              )}
              {saveState === "error" && saveError && (
                <div style={{ fontSize: 11.5, color: "var(--error)", lineHeight: 1.4 }}>
                  {saveError}
                </div>
              )}
              {!dirty && saveState === "idle" && (
                <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", textAlign: "center" }}>
                  {ctxProfile?.updated_at ? `Last saved ${timeAgo(ctxProfile.updated_at)}` : "No saves yet"}
                </div>
              )}
            </div>
          </div>

          {/* Base documents */}
          <div className="card" style={{ padding: "20px 22px" }}>
            <SectionLabel>Base documents</SectionLabel>
            <div style={{ fontSize: 12.5, color: "var(--outline)", marginBottom: 14, lineHeight: 1.5 }}>
              Kenji tailors these per role. Set one as default so Resume Lab always has a starting point.
            </div>

            {docsLoading ? (
              <div style={{ padding: "8px 0" }}>
                <div className="boot-screen" style={{ alignItems: "flex-start" }}>
                  <div className="boot-label" style={{ fontSize: 11 }}>loading documents<span className="boot-cursor">|</span></div>
                  <div className="boot-bar" style={{ width: 56 }}/>
                </div>
              </div>
            ) : docs.length === 0 ? (
              <div style={{ fontSize: 12.5, color: "var(--outline)", fontStyle: "italic", marginBottom: 12 }}>
                No documents yet. Upload a base resume to get started.
              </div>
            ) : (
              <div className="col gap-8" style={{ marginBottom: 14 }}>
                {docs.map(doc => (
                  <DocRow key={doc.id} doc={doc}
                    onDelete={() => api.deleteDocument(doc.id).then(loadDocs)}
                    onSetDefault={() => api.setDefaultDocument(doc.id).then(loadDocs)}/>
                ))}
              </div>
            )}

            <div className="row gap-8" style={{ flexWrap: "wrap" }}>
              <select className="field-input mono"
                value={uploadDocType}
                onChange={e => setUploadDocType(e.target.value as "resume" | "cover_letter")}
                style={{ width: "auto", flex: 1, minWidth: 130, fontSize: 12, padding: "6px 10px" }}>
                <option value="resume">Resume</option>
                <option value="cover_letter">Cover letter</option>
              </select>
              <button className="btn sm" disabled={uploading} onClick={() => fileRef.current?.click()}
                style={{ whiteSpace: "nowrap" }}>
                {uploading ? <><span className="spinner"/>Uploading…</> : <><Icon name="plus" size={12}/>Upload</>}
              </button>
            </div>
            <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,.md"
              style={{ display: "none" }} onChange={handleUpload}/>
            <div className="mono" style={{ fontSize: 10, color: "var(--outline)", marginTop: 8 }}>
              Accepted: PDF, DOCX, TXT, MD
            </div>
          </div>

          {/* Avatar preview */}
          <div className="card" style={{ padding: "20px 22px" }}>
            <SectionLabel>Preview</SectionLabel>
            <div className="row gap-14" style={{ alignItems: "center" }}>
              <div style={{
                width: 52, height: 52, borderRadius: "50%", flexShrink: 0,
                background: "linear-gradient(135deg, #c7a782, #82442f)",
                display: "grid", placeItems: "center",
                color: "#fff", fontFamily: "var(--font-display)",
                fontWeight: 700, fontSize: 20, letterSpacing: "-0.02em",
              }}>
                {initialsOf(displayName)}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--on-surface)" }}>{displayName}</div>
                <div className="mono" style={{ fontSize: 11, color: "var(--outline)", marginTop: 2 }}>
                  {[form.city, form.country].filter(Boolean).join(", ") || "location not set"}
                </div>
                {form.desired_job_titles.length > 0 && (
                  <div style={{ fontSize: 12, color: "var(--primary)", marginTop: 4 }}>
                    {form.desired_job_titles[0]}
                  </div>
                )}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
