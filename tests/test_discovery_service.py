from __future__ import annotations

from ai_job_hunter.services.discovery_service import build_discovery_queries, normalize_url


def test_normalize_url_greenhouse_boards_api():
    url = "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
    assert normalize_url(url) == ("greenhouse", "anthropic")


def test_normalize_url_greenhouse_job_boards():
    url = "https://job-boards.greenhouse.io/openai"
    assert normalize_url(url) == ("greenhouse", "openai")


def test_normalize_url_greenhouse_boards():
    url = "https://boards.greenhouse.io/stripe"
    assert normalize_url(url) == ("greenhouse", "stripe")


def test_normalize_url_ashby():
    url = "https://jobs.ashbyhq.com/cohere"
    assert normalize_url(url) == ("ashby", "cohere")


def test_normalize_url_ashby_with_path():
    url = "https://jobs.ashbyhq.com/cohere/some-job-id"
    assert normalize_url(url) == ("ashby", "cohere")


def test_normalize_url_lever():
    url = "https://jobs.lever.co/mistral"
    assert normalize_url(url) == ("lever", "mistral")


def test_normalize_url_workable():
    url = "https://apply.workable.com/mila-institute/"
    assert normalize_url(url) == ("workable", "mila-institute")


def test_normalize_url_recruitee():
    url = "https://acme.recruitee.com/api/offers"
    assert normalize_url(url) == ("recruitee", "acme")


def test_normalize_url_teamtailor():
    url = "https://rvezy.teamtailor.com/jobs"
    assert normalize_url(url) == ("teamtailor", "rvezy")


def test_normalize_url_unrecognized():
    assert normalize_url("https://linkedin.com/jobs/123") is None


def test_normalize_url_indeed():
    assert normalize_url("https://indeed.com/viewjob?jk=abc") is None


def test_build_discovery_queries_basic():
    profile = {
        "desired_job_titles": ["Machine Learning Engineer", "Data Scientist"],
        "country": "Canada",
        "preferred_work_mode": "remote",
    }
    queries = build_discovery_queries(profile)
    assert len(queries) == 3
    for q in queries:
        assert '"Machine Learning Engineer"' in q
        assert '"Data Scientist"' in q
        assert "Canada" in q
        assert "remote" in q
    sites = [q.split()[0] for q in queries]
    assert "site:jobs.ashbyhq.com" in sites
    assert "site:job-boards.greenhouse.io" in sites
    assert "site:jobs.lever.co" in sites


def test_build_discovery_queries_remote_only():
    profile = {
        "desired_job_titles": ["Software Engineer"],
        "country": "",
        "preferred_work_mode": "remote",
    }
    queries = build_discovery_queries(profile)
    assert len(queries) == 3
    for q in queries:
        assert "remote" in q
        assert "Canada" not in q


def test_build_discovery_queries_no_location():
    profile = {
        "desired_job_titles": ["Software Engineer"],
        "country": "",
        "preferred_work_mode": "onsite",
    }
    queries = build_discovery_queries(profile)
    assert len(queries) == 3
    for q in queries:
        assert "remote" not in q


def test_build_discovery_queries_empty_titles():
    profile = {"desired_job_titles": [], "country": "India"}
    assert build_discovery_queries(profile) == []


def test_build_discovery_queries_missing_titles_key():
    assert build_discovery_queries({}) == []
