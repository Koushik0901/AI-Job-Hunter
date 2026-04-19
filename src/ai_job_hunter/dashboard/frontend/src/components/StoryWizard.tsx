import { useEffect, useRef, useState } from "react";
import type { StoryKind, UserStoryCreate } from "../types";
import { createStory } from "../api";
import { Button } from "./ui/button";

interface Props {
  onClose: () => void;
  onComplete: (count: number) => void;
}

interface WizardStep {
  title: string;
  subtitle: string;
  kind: StoryKind;
  placeholder: string;
  hint: string;
  defaultImportance: number;
}

const STEPS: WizardStep[] = [
  {
    title: "The project you're most proud of",
    subtitle: "Think of something you built, shipped, or led that you'd love to talk about in an interview.",
    kind: "project",
    placeholder: "I built a real-time fraud detection pipeline at Acme that processed 20M events/day. The hard part was latency — we needed <50ms decisions. I redesigned the feature store from a batch job to a streaming architecture using Kafka + Redis, which brought p99 latency from 800ms to 38ms. Fraud loss dropped 42% in the first quarter after rollout.",
    hint: "What was the problem? What did you specifically do? What changed because of it?",
    defaultImportance: 5,
  },
  {
    title: "A hard problem you solved",
    subtitle: "Walk through a technical or organizational challenge that required real thought to crack.",
    kind: "role",
    placeholder: "Our ML models were drifting silently in prod — by the time we caught it via customer complaints, weeks had passed. I built a monitoring system that tracked feature distributions and model output drift, integrated it into our existing Datadog setup, and created an alerting playbook. We caught the next drift event in 2 days instead of 3 weeks.",
    hint: "Context -> your specific contribution -> outcome. The messier the problem, the better.",
    defaultImportance: 4,
  },
  {
    title: "What you want to work on next",
    subtitle: "Describe the work you want to do in your next role — problems to solve, impact to have, things to learn.",
    kind: "aspiration",
    placeholder: "I want to work closer to the model layer — I've spent the last few years on the infrastructure and deployment side, and I'm excited to dig into evaluation, alignment, and RLHF-style feedback loops. I'd love to join a team where I can move between research and production, not just productionize others' ideas.",
    hint: "What problems excite you? What do you want to get better at? What kind of team do you want to be on?",
    defaultImportance: 5,
  },
  {
    title: "Industries or domains that excite you",
    subtitle: "What areas do you care about, beyond just the technical work?",
    kind: "aspiration",
    placeholder: "I'm most energized by applications that affect real decisions at scale — healthcare diagnostics, financial crime, climate risk. I care less about the domain than about whether the system is actually used in the real world and whether the stakes are high enough to make engineering quality matter.",
    hint: "Industries, problem areas, or mission types that make you want to work harder.",
    defaultImportance: 3,
  },
  {
    title: "What collaborators praise you for",
    subtitle: "If a teammate who has worked closely with you described your style in one sentence, what would they say?",
    kind: "strength",
    placeholder: "They'd probably say I'm the person who asks the uncomfortable question in the design review — not to be difficult, but because I've seen too many projects fail because assumptions went unchecked. I also tend to over-document: I think good documentation is a gift to future-you and your team.",
    hint: "Think about recurring feedback you've received, or what you naturally do that others notice.",
    defaultImportance: 3,
  },
];

interface StepState {
  narrative: string;
  skills: string;
  outcomes: string;
  skip: boolean;
}

function emptyStep(): StepState {
  return { narrative: "", skills: "", outcomes: "", skip: false };
}

export function StoryWizard({ onClose, onComplete }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [stepStates, setStepStates] = useState<StepState[]>(STEPS.map(() => emptyStep()));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
    return () => dialogRef.current?.close();
  }, []);

  const step = STEPS[currentStep];
  const state = stepStates[currentStep];

  function updateState(patch: Partial<StepState>) {
    setStepStates((prev) => {
      const next = [...prev];
      next[currentStep] = { ...next[currentStep], ...patch };
      return next;
    });
  }

  function goNext() {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep((c) => c + 1);
      setError(null);
    }
  }

  function goPrev() {
    if (currentStep > 0) {
      setCurrentStep((c) => c - 1);
      setError(null);
    }
  }

  async function handleFinish() {
    setSaving(true);
    setError(null);
    let saved = 0;
    try {
      for (let i = 0; i < STEPS.length; i++) {
        const s = stepStates[i];
        const st = STEPS[i];
        if (s.skip || !s.narrative.trim()) continue;
        const data: UserStoryCreate = {
          title: st.title,
          narrative: s.narrative.trim(),
          skills: s.skills.split(/,|\n/).map((x) => x.trim()).filter(Boolean),
          outcomes: s.outcomes.split("\n").map((x) => x.trim()).filter(Boolean),
          kind: st.kind,
          importance: st.defaultImportance,
          source: "wizard",
          draft: false,
        };
        await createStory(data);
        saved++;
      }
      onComplete(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save stories");
    } finally {
      setSaving(false);
    }
  }

  const isLast = currentStep === STEPS.length - 1;
  const filledCount = stepStates.filter((s) => s.narrative.trim() && !s.skip).length;

  return (
    <dialog
      ref={dialogRef}
      className="story-modal story-modal--wide"
      onClick={(e) => { if (e.target === dialogRef.current) onClose(); }}
    >
      <div className="story-modal-inner">
        {/* Progress bar */}
        <div className="wizard-progress">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`wizard-progress-dot${i === currentStep ? " wizard-progress-dot--current" : i < currentStep ? " wizard-progress-dot--done" : ""}`}
              onClick={() => { setCurrentStep(i); setError(null); }}
              role="button"
              aria-label={`Step ${i + 1}`}
            />
          ))}
        </div>

        <div className="story-modal-header">
          <div>
            <p className="page-kicker">Step {currentStep + 1} of {STEPS.length}</p>
            <h2>{step.title}</h2>
            <p className="page-caption">{step.subtitle}</p>
          </div>
          <button className="story-modal-close" onClick={onClose} aria-label="Close">&#x2715;</button>
        </div>

        <div className="story-modal-body">
          {state.skip ? (
            <div className="wizard-skipped">
              <p>Skipped. <button className="story-action-btn" onClick={() => updateState({ skip: false })}>Undo</button></p>
            </div>
          ) : (
            <>
              <label className="settings-field">
                <span className="settings-field-label">Your answer</span>
                <p className="settings-field-hint">{step.hint}</p>
                <textarea
                  className="settings-field-textarea settings-field-textarea--large"
                  value={state.narrative}
                  onChange={(e) => updateState({ narrative: e.target.value })}
                  placeholder={step.placeholder}
                  autoFocus
                />
              </label>

              {(step.kind === "role" || step.kind === "project") && (
                <label className="settings-field">
                  <span className="settings-field-label">Skills involved (optional)</span>
                  <input
                    className="settings-field-input"
                    type="text"
                    value={state.skills}
                    onChange={(e) => updateState({ skills: e.target.value })}
                    placeholder="Python, PyTorch, Kafka, Redis"
                  />
                </label>
              )}

              {(step.kind === "role" || step.kind === "project") && (
                <label className="settings-field">
                  <span className="settings-field-label">Outcomes (optional, one per line)</span>
                  <textarea
                    className="settings-field-textarea"
                    value={state.outcomes}
                    onChange={(e) => updateState({ outcomes: e.target.value })}
                    placeholder={"Reduced latency by 40ms\nMentored 2 engineers"}
                  />
                </label>
              )}
            </>
          )}

          {error && <div className="settings-error">{error}</div>}
        </div>

        <div className="story-modal-footer wizard-footer">
          <button
            className="story-action-btn"
            onClick={() => updateState({ skip: true })}
            disabled={state.skip}
            type="button"
          >
            Skip this step
          </button>

          <div className="wizard-footer-nav">
            {currentStep > 0 && (
              <button className="story-action-btn" onClick={goPrev} type="button">Back</button>
            )}
            {!isLast ? (
              <Button variant="primary" onClick={goNext}>Next</Button>
            ) : (
              <Button
                variant="primary"
                onClick={() => void handleFinish()}
                disabled={saving || filledCount === 0}
              >
                {saving ? "Saving..." : `Save ${filledCount} stor${filledCount === 1 ? "y" : "ies"}`}
              </Button>
            )}
          </div>
        </div>
      </div>
    </dialog>
  );
}
