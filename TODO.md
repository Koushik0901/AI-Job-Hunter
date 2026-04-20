# TODO

## (6) Autofill HITL + learning loop

After the Chrome extension autofills a form, show a confirmation step so the user
can review and correct individual fields before submitting. Persist corrections back
to the system (profile or per-job overrides) so future autofills improve over time.

**Scope:**
- Extension: post-autofill confirmation UI (side panel or overlay) listing filled fields
- User can edit any field inline before confirming
- On confirm, diff corrected fields against filled values and POST corrections to backend
- Backend: store per-field corrections keyed by (job_id or ats_domain, field_name)
- Use stored corrections to pre-seed future autofill for same ATS
