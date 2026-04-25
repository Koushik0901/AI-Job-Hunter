// Kenji — User Stories, wired to /api/stories.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type InterviewTurn, type UserStory } from "../api";
import { useData } from "../DataContext";
import { Icon } from "./ui";

type KindColor = "experience" | "project" | "preference" | "trait";

const KIND_COLORS: Record<KindColor, string> = {
  experience: "#7FB4FF",
  project:    "#F6C66A",
  preference: "#D4FF3A",
  trait:      "#E89BC9",
};

// Backend story.kind is "role"|"project"|"aspiration"|"strength" — map to UI palette.
function kindAlias(k: string): KindColor {
  if (k === "project") return "project";
  if (k === "aspiration") return "preference";
  if (k === "strength") return "trait";
  return "experience";
}

function StoryCard({ story, expanded, onToggle }: {
  story: UserStory; expanded: boolean; onToggle: () => void;
}) {
  const alias = kindAlias(story.kind);
  const c = KIND_COLORS[alias];
  return (
    <div className="card story-card" style={{ padding: 0, overflow: "hidden", cursor: "pointer", transition: "border-color 120ms" }}
      role="button" tabIndex={0}
      onClick={onToggle}
      onKeyDown={e => (e.key === "Enter" || e.key === " ") && onToggle()}>
      <div className="row-top gap-14" style={{ padding: "16px 18px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row gap-10">
            <span className="mono" style={{ fontSize: 9.5, color: c, letterSpacing: "0.14em", textTransform: "uppercase" }}>
              {alias}
            </span>
            <span className="mono" style={{ fontSize: 10, color: "var(--outline)" }}>s{story.id}</span>
            {story.time_period && <span className="mono" style={{ fontSize: 10, color: "var(--outline)", marginLeft: "auto" }}>{story.time_period}</span>}
          </div>
          <div style={{ fontSize: 16, fontWeight: 400, marginTop: 6, letterSpacing: "-0.01em", color: "var(--on-surface)", fontFamily: "var(--font-serif)", fontStyle: "italic" }}>
            {story.title}
          </div>
          {story.role_context && <div style={{ fontSize: 12, color: "var(--on-surface-variant)", marginTop: 3 }}>{story.role_context}</div>}
          <div style={{ fontSize: 13, color: "var(--on-surface)", marginTop: 10, lineHeight: 1.6 }}>
            {expanded ? story.narrative : story.narrative.slice(0, 140) + (story.narrative.length > 140 ? "…" : "")}
          </div>
          {expanded && story.outcomes.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: "var(--on-surface-variant)", lineHeight: 1.6 }}>
              {story.outcomes.map((o, i) => <li key={i}>{o}</li>)}
            </ul>
          )}
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 12 }}>
            {story.tags.map(t => <span key={t} className="chip mono">{t}</span>)}
            {story.skills.slice(0, 6).map(s => <span key={`sk-${s}`} className="chip mono">{s}</span>)}
          </div>
        </div>
      </div>
    </div>
  );
}

const COVERAGE_LABELS: Record<string, string> = {
  IMPACT: "Impact",
  SKILLS: "Skills",
  ROLE_TARGET: "Role",
  WORK_STYLE: "Style",
  MOTIVATION: "Goals",
  SENIORITY: "Scope",
};
const ALL_AREAS = Object.keys(COVERAGE_LABELS);
const MAX_QUESTIONS = 8;

export function Stories() {
  const { stories, refreshStories, refreshAll, profile } = useData();
  const [expanded, setExpanded] = useState<number | null>(null);

  // Interview state
  const [conversation, setConversation] = useState<InterviewTurn[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState<string | null>(null);
  const [covered, setCovered] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [loadingNext, setLoadingNext] = useState(false);
  const [interviewDone, setInterviewDone] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const initialized = useRef(false);

  const firstName = (profile?.full_name || "you").split(/\s+/)[0];

  const counts = useMemo(() => {
    const byKind: Record<string, number> = {};
    stories.forEach(s => { byKind[s.kind] = (byKind[s.kind] ?? 0) + 1; });
    return byKind;
  }, [stories]);

  // Fetch opener on mount (returns instantly — no LLM on empty conversation)
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    api.interviewNext([]).then(res => {
      setCurrentQuestion(res.next_question);
    }).catch(() => {/* keep null — user can retry */});
  }, []);

  async function submitAnswer() {
    if (!draft.trim() || loadingNext || !currentQuestion) return;
    const turn: InterviewTurn = { question: currentQuestion, answer: draft.trim() };
    const newConversation = [...conversation, turn];
    setConversation(newConversation);
    setDraft("");
    setErr(null);

    if (newConversation.length >= MAX_QUESTIONS) {
      setInterviewDone(true);
      setCovered(ALL_AREAS);
      return;
    }

    setLoadingNext(true);
    try {
      const res = await api.interviewNext(newConversation);
      setCovered(res.covered);
      if (res.done || !res.next_question) {
        setInterviewDone(true);
      } else {
        setCurrentQuestion(res.next_question);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load next question");
    } finally {
      setLoadingNext(false);
    }
  }

  async function finishInterview() {
    if (finishing || conversation.length === 0) return;
    setFinishing(true); setErr(null);
    try {
      const res = await api.interviewFinish(conversation);

      // Bulk-create stories
      for (const s of res.stories) {
        await api.createStory({
          title: s.title,
          narrative: s.narrative,
          kind: s.kind as "role" | "project" | "aspiration" | "strength",
          skills: s.skills,
          outcomes: s.outcomes,
          tags: s.tags,
          time_period: s.time_period ?? undefined,
          source: "wizard",
          draft: false,
        });
      }

      // Patch profile with extracted signals (merge into full profile — PUT requires complete payload)
      const patch = res.profile_patch;
      let profileChanged = false;
      if (profile) {
        const updated = { ...profile };
        if (patch.skills.length > 0) {
          const merged = [...new Set([...(profile.skills || []), ...patch.skills])];
          if (merged.length !== (profile.skills || []).length) {
            updated.skills = merged;
            profileChanged = true;
          }
        }
        if (patch.desired_job_titles.length > 0) {
          const merged = [...new Set([...(profile.desired_job_titles || []), ...patch.desired_job_titles])];
          if (merged.length !== (profile.desired_job_titles || []).length) {
            updated.desired_job_titles = merged;
            profileChanged = true;
          }
        }
        if (patch.preferred_work_mode && !profile.preferred_work_mode) {
          updated.preferred_work_mode = patch.preferred_work_mode;
          profileChanged = true;
        }
        if (patch.narrative_intent && !profile.narrative_intent) {
          updated.narrative_intent = patch.narrative_intent;
          profileChanged = true;
        }
        if (profileChanged) {
          await api.updateProfile(updated);
        }
      }

      await refreshStories();
      if (profileChanged) refreshAll();
      if (res.stories.length === 0) {
        setErr("Kenji couldn't extract stories from your answers — the model may have returned an unexpected response. Try again or rephrase your answers.");
        setFinishing(false);
        return;
      }
      setSavedCount(res.stories.length);
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setFinishing(false);
    }
  }

  function restartInterview() {
    setConversation([]);
    setCovered([]);
    setInterviewDone(false);
    setSaved(false);
    setSavedCount(0);
    setDraft("");
    setErr(null);
    setCurrentQuestion(null);
    initialized.current = false;
    api.interviewNext([]).then(res => {
      setCurrentQuestion(res.next_question);
      initialized.current = true;
    }).catch(() => {});
  }

  const questionIndex = conversation.length;
  const allCovered = ALL_AREAS.every(a => covered.includes(a));

  return (
    <div className="content" style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 36, maxWidth: 1480 }}>
      <div>
        <div style={{ marginBottom: 28, paddingBottom: 24, borderBottom: "1px solid var(--outline-variant)" }}>
          <div className="overline" style={{ marginBottom: 14 }}>User stories · {stories.length} captured</div>
          <div className="headline">
            {firstName} is more<br/>than a <em>résumé.</em>
          </div>
          <div style={{ fontSize: 13.5, color: "var(--on-surface-variant)", marginTop: 14, maxWidth: 560, lineHeight: 1.6 }}>
            Stories ground everything Kenji does — ranking, tailoring, cover letters. Every edit to your application traces back to a story you've written. Nothing is invented.
          </div>
        </div>

        <div className="row gap-8" style={{ marginBottom: 18, flexWrap: "wrap" }}>
          <span className="chip accent mono">{stories.length} captured</span>
          {(["role", "project", "aspiration", "strength"] as const).map(k => counts[k] > 0 && (
            <span key={k} className="chip mono">{counts[k]} {k}</span>
          ))}
        </div>

        {stories.length === 0 && (
          <div className="card" style={{ padding: 24, textAlign: "center" }}>
            <div className="serif italic" style={{ fontSize: 18, color: "var(--on-surface)" }}>No stories yet.</div>
            <div style={{ fontSize: 12.5, color: "var(--on-surface-variant)", marginTop: 8 }}>
              Answer Kenji's questions on the right — your replies become structured stories automatically.
            </div>
          </div>
        )}

        <div className="col gap-10 stagger">
          {stories.map(s => (
            <StoryCard key={s.id} story={s}
              expanded={expanded === s.id}
              onToggle={() => setExpanded(expanded === s.id ? null : s.id)}/>
          ))}
        </div>
      </div>

      {/* Interview panel */}
      <div style={{ position: "sticky", top: 90, alignSelf: "start" }}>
        <div className="card lifted" style={{ padding: 22 }}>

          {/* Header */}
          <div className="row gap-12" style={{ marginBottom: 18 }}>
            <div className="agent-avatar">k</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 500, fontSize: 13 }}>Kenji interview</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--outline)", letterSpacing: "0.04em", marginTop: 2 }}>
                adaptive · up to {MAX_QUESTIONS} questions
              </div>
            </div>
            {questionIndex > 0 && !interviewDone && (
              <div className="mono" style={{ fontSize: 10, color: "var(--outline)", flexShrink: 0 }}>
                {questionIndex} / {MAX_QUESTIONS}
              </div>
            )}
          </div>

          {/* Coverage dots */}
          <div className="row gap-6" style={{ marginBottom: 18, flexWrap: "wrap" }}>
            {ALL_AREAS.map(area => {
              const isCovered = covered.includes(area);
              return (
                <div key={area} style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "3px 8px", borderRadius: 99,
                  background: isCovered ? "var(--primary-tint)" : "var(--sc-high)",
                  transition: "background 300ms",
                }}>
                  <div style={{
                    width: 5, height: 5, borderRadius: "50%",
                    background: isCovered ? "var(--primary)" : "var(--outline-variant)",
                    transition: "background 300ms",
                  }}/>
                  <span className="mono" style={{
                    fontSize: 9.5, letterSpacing: "0.08em",
                    color: isCovered ? "var(--primary)" : "var(--outline)",
                    fontWeight: isCovered ? 600 : 400,
                  }}>
                    {COVERAGE_LABELS[area]}
                  </span>
                </div>
              );
            })}
          </div>

          {/* ── Done / Saved state ── */}
          {saved ? (
            <div className="col gap-14" style={{ alignItems: "center", padding: "16px 0", textAlign: "center" }}>
              <div style={{ fontSize: 32 }}>✓</div>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, color: "var(--primary)" }}>
                {savedCount} {savedCount === 1 ? "story" : "stories"} added
              </div>
              <div style={{ fontSize: 12.5, color: "var(--on-surface-variant)", lineHeight: 1.5 }}>
                Your profile and skill list have been updated with what Kenji extracted.
              </div>
              <button className="btn ghost sm" onClick={restartInterview}>
                <Icon name="plus" size={12}/>Start another interview
              </button>
            </div>

          /* ── Done, ready to save ── */
          ) : interviewDone ? (
            <div className="col gap-14">
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 600, fontSize: 16, color: "var(--on-surface)", lineHeight: 1.4 }}>
                That's enough to work with.
              </div>
              <div style={{ fontSize: 13, color: "var(--on-surface-variant)", lineHeight: 1.6 }}>
                Kenji will extract {conversation.length > 1 ? "stories and profile signals" : "a story"} from your {conversation.length} {conversation.length === 1 ? "answer" : "answers"} — skills, role targets, work preferences, and career intent.
              </div>
              {err && <div className="mono" style={{ fontSize: 11, color: "var(--error)" }}>{err}</div>}
              <div className="row gap-8">
                <button className="btn ghost sm" onClick={restartInterview} disabled={finishing}>
                  Start over
                </button>
                <div className="spacer"/>
                <button className="btn primary sm" onClick={finishInterview} disabled={finishing}>
                  {finishing
                    ? <><span className="spinner"/>Extracting…</>
                    : <>Save all<Icon name="arrow" size={11}/></>}
                </button>
              </div>
            </div>

          /* ── Active question ── */
          ) : (
            <>
              {loadingNext ? (
                <div className="col gap-10" style={{ marginBottom: 16 }}>
                  <div className="skeleton" style={{ height: 14, width: "60%" }}/>
                  <div className="skeleton" style={{ height: 14, width: "85%" }}/>
                  <div className="skeleton" style={{ height: 14, width: "45%" }}/>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--outline)", marginTop: 4 }}>thinking…</div>
                </div>
              ) : currentQuestion ? (
                <div className="serif italic" style={{ fontSize: 20, lineHeight: 1.4, color: "var(--on-surface)", letterSpacing: "-0.01em", marginBottom: 16 }}>
                  "{currentQuestion}"
                </div>
              ) : (
                <div className="skeleton" style={{ height: 60, marginBottom: 16 }}/>
              )}

              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitAnswer(); }}
                placeholder="Answer naturally — Kenji adapts the next question to what you say."
                aria-label="Your interview answer"
                disabled={loadingNext || !currentQuestion}
                style={{
                  width: "100%",
                  border: "1px solid var(--outline-variant)",
                  borderRadius: 8, padding: "12px 14px",
                  minHeight: 120, resize: "vertical",
                  background: "var(--surface)", fontSize: 13, lineHeight: 1.55,
                  color: "var(--on-surface)", opacity: loadingNext ? 0.5 : 1,
                }}
                onFocus={e => (e.target as HTMLTextAreaElement).style.borderColor = "var(--outline)"}
                onBlur={e => (e.target as HTMLTextAreaElement).style.borderColor = "var(--outline-variant)"}
              />

              {err && <div className="mono" style={{ fontSize: 11, color: "var(--error)", marginTop: 6 }}>{err}</div>}

              <div className="row gap-6" style={{ marginTop: 10 }}>
                {questionIndex > 0 && (
                  <button className="btn ghost sm" disabled={loadingNext}
                    onClick={() => {
                      const prev = conversation[conversation.length - 1];
                      setConversation(conversation.slice(0, -1));
                      setCurrentQuestion(prev.question);
                      setDraft(prev.answer);
                      setCovered(covered.filter(a => !ALL_AREAS.slice(covered.indexOf(a)).includes(a)));
                    }}>
                    Back
                  </button>
                )}
                <div className="spacer"/>
                {(allCovered || questionIndex >= 4) && (
                  <button className="btn ghost sm" disabled={loadingNext}
                    onClick={() => setInterviewDone(true)}>
                    Done
                  </button>
                )}
                <button className="btn ghost sm" disabled={loadingNext || !currentQuestion}
                  onClick={async () => {
                    // Skip: advance without saving this answer
                    setDraft("");
                    setLoadingNext(true);
                    try {
                      const res = await api.interviewNext(conversation);
                      setCovered(res.covered);
                      if (res.done || !res.next_question) setInterviewDone(true);
                      else setCurrentQuestion(res.next_question);
                    } catch { /* keep current */ } finally { setLoadingNext(false); }
                  }}>
                  Skip
                </button>
                <button className="btn primary sm"
                  disabled={!draft.trim() || loadingNext || !currentQuestion}
                  onClick={submitAnswer}>
                  {loadingNext ? <><span className="spinner"/>…</> : <>Next<Icon name="arrow" size={11}/></>}
                </button>
              </div>

              <div className="mono" style={{ marginTop: 10, fontSize: 10, color: "var(--outline)", textAlign: "right" }}>
                {draft.trim() ? "⌘↵ to submit" : ""}
              </div>
            </>
          )}
        </div>

        <div className="card" style={{ padding: 16, marginTop: 14, background: "var(--sc-low)" }}>
          <div className="row-top gap-10">
            <Icon name="sparkles" size={13}/>
            <div style={{ fontSize: 12, color: "var(--on-surface-variant)", lineHeight: 1.55 }}>
              <span style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 14, color: "var(--on-surface)" }}>Tip.</span>{" "}
              Upload your résumé in Profile — Kenji will extract draft stories from it so you only edit, not type from scratch.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
