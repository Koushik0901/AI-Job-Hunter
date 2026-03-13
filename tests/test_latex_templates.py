from dashboard.backend.latex_resume import (
    get_cover_letter_template_source,
    get_resume_template_source,
)


def test_template_source_falls_back_by_artifact_kind(tmp_path, monkeypatch):
    resume_dir = tmp_path / "resume_templates"
    cover_letter_dir = tmp_path / "cover_letter_templates"
    resume_dir.mkdir()
    cover_letter_dir.mkdir()

    monkeypatch.setenv("RESUME_TEMPLATE_DIR", str(resume_dir))
    monkeypatch.setenv("COVER_LETTER_TEMPLATE_DIR", str(cover_letter_dir))

    resume_source = get_resume_template_source("missing")
    cover_letter_source = get_cover_letter_template_source("missing")

    assert "<<SUMMARY_SECTION>>" in resume_source
    assert "<<BODY_PARAGRAPHS>>" in cover_letter_source
    assert "<<SUMMARY_SECTION>>" not in cover_letter_source
