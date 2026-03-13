# TODO

## Now (Current Sprint)

### 1) Swarm quality deep-dive (50-case benchmark)
- [ ] Analyze latest `eval/results/swarm_benchmark_*.json` for:
  - top `failed_move_reasons` by artifact type
  - all negative `score_delta` cases (resume + cover letter)
- [ ] Produce ranked fix plan:
  - prompt-side fixes
  - parser/apply-engine fixes
  - claim-policy/tone-guard tuning
- [ ] Track targets for next run:
  - apply success `>= 88%`
  - out-of-region violations `= 0`
  - compile regressions `= 0`
  - negative `score_delta` cases `<= 5%`
- [ ] Defer full benchmark rerun + full test sweep until Agents V2 orchestration tasks are complete.

### 2) Prompt alignment for legal moves (YAML-only)
- [ ] Ensure all rewriter prompts emit legal `moves` schema consistently.
- [ ] Ensure parsed line/block context + allowed regions are always supplied.
- [ ] Keep prompts in `prompts/*.yaml` only (no hardcoded prompt bodies).

---

## Next

### 3) Advanced controlled ops completion
- [ ] Verify/finish `swap_blocks` constraints (resume only, same section + compatible block types).
- [ ] Verify/finish bounded `insert_line_after` policy for cover letter (max 1 per cycle + allowed paragraph regions).
- [ ] Strengthen legacy marker compatibility checks.

### 4) Frontend swarm run clarity
- [ ] Finalize move table UX (`fix_id`, `op`, target ID, status).
- [ ] Finalize grouped apply outcomes (`applied/failed/warnings`).
- [ ] Finalize policy-failure badge/count presentation.

### 5) QA hardening
- [ ] Keep unit test suite complete for parser/move-policy/deterministic apply/truthfulness checks.
- [ ] Keep integration tests stable for resume + cover-letter start → status → confirm-save → recompile + cancel.

---

## Next (Agents V2 follow-through)

### 6) Agents V2 benchmark sign-off
- [ ] Run full 50-case swarm benchmark after the V2 orchestration pass.
- [ ] Compare V2 benchmark output against pre-V2 baseline.
- [ ] Analyze worst `failed_move_reasons` and negative `score_delta` cases from V2 runs.

### 7) Agents V2 UI polish
- [ ] Finalize timeline move table UX (`fix_id`, `op`, target ID, status).
- [ ] Finalize grouped apply outcomes (`applied/failed/warnings`) in the editor timeline.
- [ ] Finalize policy-failure badge/count presentation.

---

## Done (Kept for context)

### Swarm legal-move foundation
- [x] Canonical LaTeX parser (resume + cover letter) with marker support.
- [x] Legal move schema and deterministic apply report structure.
- [x] Deterministic conflict filtering (`skipped_conflict`) in verify stage.
- [x] Graph wiring: `prepare_edit_context -> verify_moves -> apply`.

### Grounded optimization foundation
- [x] `candidate_evidence_assets` persistence.
- [x] Evidence Vault API (`GET/PUT /api/profile/evidence-assets`).
- [x] Profile UI Evidence Vault tab.
- [x] Swarm grounding integration (`evidence_context`, brag doc, project cards, do-not-claim).
- [x] Optional Qdrant index + lexical fallback.
- [x] Hybrid evidence retrieval path in both swarms.
- [x] Claim validator with truth-source precedence.
- [x] Run history persistence (`artifact_ai_runs`, `artifact_ai_run_events`).
- [x] Timeline upgrades with evidence snippets/citations + policy badges.
- [x] Grounded edit provenance (`supported_by` validation).
- [x] Cover-letter tone guard.
- [x] Evidence asset size limits + sanitization.

### Acceptance baseline
- [x] Benchmark harness (`eval/swarm_benchmark.py`) with acceptance gates.
- [x] E2E integration tests for resume/cover-letter run lifecycle.

### Agents V2 orchestration
- [x] Resume JD Decomposer
- [x] Resume Evidence Miner
- [x] Resume Planner
- [x] Resume Rewriter
- [x] Resume Verifier / Consistency Guard
- [x] Resume Scorer wiring in explicit multi-agent graph
- [x] Cover-letter JD Decomposer
- [x] Cover-letter Evidence Miner
- [x] Cover-letter Narrative Planner
- [x] Cover-letter Draft / Refiner wiring
- [x] Cover-letter Tone Guard
- [x] Cover-letter Scorer wiring in explicit multi-agent graph
- [x] Cover-letter Rewriter wiring in explicit multi-agent graph
- [x] Controller stop conditions (cycles, delta threshold, non-negotiables, edit budget)
- [x] Frontend timeline support for JD target spec, evidence/planning, and tone-guard stages
