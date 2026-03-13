# 🚀 ATS Integrations

Supported connectors:
- Greenhouse
- Lever
- Ashby
- Workable
- SmartRecruiters
- Recruitee

Plus HN hiring thread ingestion.

---

## ✨ Connector Contract

Each fetcher returns normalized job records with common fields:
- company
- title
- location
- url
- posted
- ats
- description (when available)

---

## ✨ Source Selection

Scrape input comes from `company_sources` table (`enabled=1`).

---

## ✨ Practical Caveats

- Some ATS endpoints return 200 with zero jobs for bad slugs.
- Probe and add flows filter low-signal false positives.
