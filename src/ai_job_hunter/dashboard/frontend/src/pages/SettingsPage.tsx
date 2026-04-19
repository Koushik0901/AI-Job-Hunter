import { useCallback, useEffect, useRef, useState } from "react";
import { putProfile, listBaseDocuments, uploadBaseDocument, deleteBaseDocument, setDefaultBaseDocument } from "../api";
import { useDashboardData } from "../contexts/DashboardDataContext";
import { Button } from "../components/ui/button";
import type { BaseDocument, CandidateProfile } from "../types";

function listToText(items: string[] | null | undefined): string {
  return (items ?? []).join("\n");
}

function textToList(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function SettingsPage() {
  const { profile, refreshData } = useDashboardData();
  const [profileDraft, setProfileDraft] = useState<Partial<CandidateProfile>>({});
  const [skillsText, setSkillsText] = useState("");
  const [titlesText, setTitlesText] = useState("");
  const [roleFamiliesText, setRoleFamiliesText] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [docs, setDocs] = useState<BaseDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [expandedDocId, setExpandedDocId] = useState<number | null>(null);

  const resumeInputRef = useRef<HTMLInputElement>(null) as React.RefObject<HTMLInputElement>;
  const clInputRef = useRef<HTMLInputElement>(null) as React.RefObject<HTMLInputElement>;

  const loadDocs = useCallback(async () => {
    try {
      const list = await listBaseDocuments();
      setDocs(list);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (profile) {
      setProfileDraft({
        years_experience: profile.years_experience ?? 0,
        requires_visa_sponsorship: profile.requires_visa_sponsorship ?? false,
        full_name: profile.full_name ?? "",
        email: profile.email ?? "",
        phone: profile.phone ?? "",
        linkedin_url: profile.linkedin_url ?? "",
        portfolio_url: profile.portfolio_url ?? "",
        city: profile.city ?? "",
        country: profile.country ?? "Canada",
      });
      setSkillsText(listToText(profile.skills));
      setTitlesText(listToText(profile.desired_job_titles));
      setRoleFamiliesText(listToText(profile.target_role_families));
    }
    void loadDocs();
  }, [profile, loadDocs]);

  async function handleSaveProfile() {
    if (!profile) return;
    setProfileSaving(true);
    setProfileError(null);
    try {
      await putProfile({
        ...profile,
        ...profileDraft,
        skills: textToList(skillsText),
        desired_job_titles: textToList(titlesText),
        target_role_families: textToList(roleFamiliesText),
      } as CandidateProfile);
      await refreshData({ force: true });
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 2200);
    } catch (error: unknown) {
      setProfileError(error instanceof Error ? error.message : "Save failed");
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleUpload(file: File, docType: "resume" | "cover_letter") {
    setUploading(true);
    setUploadError(null);
    try {
      await uploadBaseDocument(file, docType);
      await loadDocs();
    } catch (error: unknown) {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteBaseDocument(id);
      setDocs((prev) => prev.filter((doc) => doc.id !== id));
    } catch {
      // silent
    }
  }

  async function handleSetDefault(id: number) {
    try {
      const updated = await setDefaultBaseDocument(id);
      setDocs((prev) => prev.map((doc) => doc.doc_type === updated.doc_type ? { ...doc, is_default: doc.id === id } : doc));
    } catch {
      // silent
    }
  }

  const resumeDocs = docs.filter((doc) => doc.doc_type === "resume");
  const coverDocs = docs.filter((doc) => doc.doc_type === "cover_letter");

  const field = (
    key: keyof typeof profileDraft,
    label: string,
    placeholder = "",
    type = "text",
  ) => (
    <label className="settings-field">
      <span className="settings-field-label">{label}</span>
      <input
        className="settings-field-input"
        type={type}
        placeholder={placeholder}
        value={String((profileDraft[key] as string | number | boolean | null | undefined) ?? "")}
        onChange={(e) => {
          const nextValue = type === "number" ? Number(e.target.value || 0) : e.target.value;
          setProfileDraft((prev) => ({ ...prev, [key]: nextValue }));
        }}
      />
    </label>
  );

  return (
    <div className="dashboard-page settings-page-refined">
      <section className="page-rail settings-rail">
        <div className="page-rail-copy">
          <p className="page-kicker">Settings</p>
          <h1 className="page-title">Profile and document base</h1>
          <p className="page-caption">
            Keep the personal identity, search targets, and source documents clean so the rest of the system stays reliable.
          </p>
        </div>
        <div className="page-rail-meta">
          <span className="page-meta-pill">{resumeDocs.length} resumes</span>
          <span className="page-meta-pill">{coverDocs.length} cover letters</span>
        </div>
      </section>

      <div className="settings-layout">
        <div className="settings-main-column">
          <section className="settings-surface">
            <div className="settings-surface-head">
              <div>
                <p className="page-kicker">Identity</p>
                <h2>Autofill and contact details</h2>
              </div>
            </div>
            <div className="settings-fields">
              {field("full_name", "Full name", "Jane Doe")}
              {field("email", "Email", "jane@example.com", "email")}
              {field("phone", "Phone", "+1 (555) 000-0000", "tel")}
              {field("linkedin_url", "LinkedIn URL", "https://linkedin.com/in/username")}
              {field("portfolio_url", "Portfolio / GitHub", "https://github.com/username")}
              {field("city", "City", "Vancouver")}
              {field("country", "Country", "Canada")}
              {field("years_experience", "Years of experience", "3", "number")}
            </div>
          </section>

          <section className="settings-surface">
            <div className="settings-surface-head">
              <div>
                <p className="page-kicker">Search preferences</p>
                <h2>What the system should optimize for</h2>
              </div>
            </div>
            <div className="settings-preference-grid">
              <label className="settings-field settings-field--full">
                <span className="settings-field-label">Desired job titles</span>
                <textarea
                  className="settings-field-textarea"
                  value={titlesText}
                  onChange={(e) => setTitlesText(e.target.value)}
                  placeholder={"Senior ML Engineer\nApplied Scientist\nData Scientist"}
                />
              </label>

              <label className="settings-field settings-field--full">
                <span className="settings-field-label">Target role families</span>
                <textarea
                  className="settings-field-textarea"
                  value={roleFamiliesText}
                  onChange={(e) => setRoleFamiliesText(e.target.value)}
                  placeholder={"Machine Learning\nApplied AI\nData Science"}
                />
              </label>

              <label className="settings-field settings-field--full">
                <span className="settings-field-label">Core skills</span>
                <textarea
                  className="settings-field-textarea settings-field-textarea--large"
                  value={skillsText}
                  onChange={(e) => setSkillsText(e.target.value)}
                  placeholder={"Python\nPyTorch\nLLM evaluation\nMLOps"}
                />
              </label>

              <label className="settings-toggle-card">
                <div>
                  <span className="settings-field-label">Visa sponsorship</span>
                  <p>Use this in matching and recommendation logic.</p>
                </div>
                <input
                  type="checkbox"
                  checked={Boolean(profileDraft.requires_visa_sponsorship)}
                  onChange={(e) => setProfileDraft((prev) => ({ ...prev, requires_visa_sponsorship: e.target.checked }))}
                />
              </label>
            </div>
            {profileError ? <div className="settings-error">{profileError}</div> : null}
            <div className="settings-save-row">
              <Button type="button" variant="primary" onClick={() => void handleSaveProfile()} disabled={profileSaving}>
                {profileSaving ? "Saving..." : "Save profile"}
              </Button>
              {profileSaved ? <span className="settings-saved-badge">Saved</span> : null}
            </div>
          </section>
        </div>

        <div className="settings-side-column">
          <section className="settings-surface">
            <div className="settings-surface-head">
              <div>
                <p className="page-kicker">Document vault</p>
                <h2>Base resumes and cover letters</h2>
              </div>
            </div>
            <p className="settings-copy-soft">
              These files are the source material for generated application artifacts. Keep one strong default for each document type.
            </p>

            <DocSection
              title="Resumes"
              docs={resumeDocs}
              docType="resume"
              uploading={uploading}
              expandedDocId={expandedDocId}
              onExpand={(id) => setExpandedDocId((prev) => prev === id ? null : id)}
              onUpload={(file) => handleUpload(file, "resume")}
              onDelete={handleDelete}
              onSetDefault={handleSetDefault}
              fileInputRef={resumeInputRef}
            />

            <DocSection
              title="Cover letters"
              docs={coverDocs}
              docType="cover_letter"
              uploading={uploading}
              expandedDocId={expandedDocId}
              onExpand={(id) => setExpandedDocId((prev) => prev === id ? null : id)}
              onUpload={(file) => handleUpload(file, "cover_letter")}
              onDelete={handleDelete}
              onSetDefault={handleSetDefault}
              fileInputRef={clInputRef}
            />

            {uploadError ? <div className="settings-error">{uploadError}</div> : null}
          </section>
        </div>
      </div>
    </div>
  );
}

interface DocSectionProps {
  title: string;
  docs: BaseDocument[];
  docType: "resume" | "cover_letter";
  uploading: boolean;
  expandedDocId: number | null;
  onExpand: (id: number) => void;
  onUpload: (file: File) => void;
  onDelete: (id: number) => void;
  onSetDefault: (id: number) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
}

function DocSection({
  title,
  docs,
  docType,
  uploading,
  expandedDocId,
  onExpand,
  onUpload,
  onDelete,
  onSetDefault,
  fileInputRef,
}: DocSectionProps) {
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onUpload(file);
    e.target.value = "";
  }

  return (
    <div className="settings-doc-block">
      <div className="settings-doc-block-head">
        <div>
          <span className="settings-doc-title">{title}</span>
          <small>{docs.length} file{docs.length === 1 ? "" : "s"}</small>
        </div>
        <button className="settings-doc-upload" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? "Uploading..." : `Upload ${docType === "resume" ? "resume" : "letter"}`}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
      </div>

      {docs.length === 0 ? (
        <div className="settings-doc-empty">No {title.toLowerCase()} uploaded yet.</div>
      ) : (
        <ul className="settings-doc-list">
          {docs.map((doc) => (
            <li key={doc.id} className="settings-doc-item">
              <div className="settings-doc-row">
                <div className="settings-doc-copy">
                  <strong>{doc.filename}</strong>
                  <small>{doc.created_at.slice(0, 10)}</small>
                </div>
                <div className="settings-doc-actions">
                  {doc.is_default ? <span className="doc-default-badge">Default</span> : null}
                  {!doc.is_default ? (
                    <button className="doc-action-btn" onClick={() => onSetDefault(doc.id)}>Set default</button>
                  ) : null}
                  <button className="doc-action-btn" onClick={() => onExpand(doc.id)}>
                    {expandedDocId === doc.id ? "Hide" : "Preview"}
                  </button>
                  <button className="doc-action-btn doc-action-btn--delete" onClick={() => onDelete(doc.id)}>Delete</button>
                </div>
              </div>
              {expandedDocId === doc.id ? <pre className="doc-preview">{doc.content_md}</pre> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
