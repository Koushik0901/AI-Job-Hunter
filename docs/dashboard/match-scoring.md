# 🚀 Match Scoring Rubric

Match scoring is deterministic and used across board ranking + detail view.

---

## ✨ Inputs

Profile signals:
- years of experience
- skills
- target role families
- visa requirement
- education

Job signals:
- title
- enrichment fields (when available)

---

## ✨ Output

- `score` in `0..100`
- `band` in `{excellent, good, fair, low}`
- `breakdown` and rationale fields for UI

---

## ✨ Band Thresholds

- `excellent`: `>=80`
- `good`: `65..79`
- `fair`: `45..64`
- `low`: `<45`

---

## ✨ Practical Notes

- Higher overlap on required skills and role alignment drives score up.
- Visa mismatch and strong seniority mismatch drive score down.
- Score is clamped to keep output stable and comparable.
