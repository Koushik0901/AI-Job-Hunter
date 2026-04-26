from __future__ import annotations

import textwrap

from ai_job_hunter.services.company_source_service import parse_career_ops_portals


_SAMPLE_YAML = textwrap.dedent("""\
    tracked_companies:
      - name: Anthropic
        careers_url: https://job-boards.greenhouse.io/anthropic
        api: https://boards-api.greenhouse.io/v1/boards/anthropic/jobs
        enabled: true

      - name: Cohere
        careers_url: https://jobs.ashbyhq.com/cohere
        enabled: true

      - name: Mistral AI
        careers_url: https://jobs.lever.co/mistral
        enabled: true

      - name: Retool
        careers_url: https://retool.com/careers
        scan_method: websearch
        enabled: true

      - name: OpenAI
        careers_url: https://openai.com/careers
        scan_method: websearch
        scan_query: 'site:openai.com/careers "AI Engineer"'
        enabled: true

      - name: Cohere Duplicate
        careers_url: https://jobs.ashbyhq.com/cohere
        enabled: true
""")


def test_parse_career_ops_portals_greenhouse_api_field():
    results = parse_career_ops_portals(_SAMPLE_YAML)
    entry = next((r for r in results if r[0] == "Anthropic"), None)
    assert entry == ("Anthropic", "greenhouse", "anthropic")


def test_parse_career_ops_portals_ashby_careers_url():
    results = parse_career_ops_portals(_SAMPLE_YAML)
    entry = next((r for r in results if r[0] == "Cohere"), None)
    assert entry == ("Cohere", "ashby", "cohere")


def test_parse_career_ops_portals_lever_careers_url():
    results = parse_career_ops_portals(_SAMPLE_YAML)
    entry = next((r for r in results if r[0] == "Mistral AI"), None)
    assert entry == ("Mistral AI", "lever", "mistral")


def test_parse_career_ops_portals_skips_websearch_branded():
    results = parse_career_ops_portals(_SAMPLE_YAML)
    names = [r[0] for r in results]
    assert "Retool" not in names
    assert "OpenAI" not in names


def test_parse_career_ops_portals_deduplicates():
    results = parse_career_ops_portals(_SAMPLE_YAML)
    ashby_cohere = [r for r in results if r[1] == "ashby" and r[2] == "cohere"]
    assert len(ashby_cohere) == 1


def test_parse_career_ops_portals_invalid_yaml():
    assert parse_career_ops_portals("not: valid: yaml: [[[") == []


def test_parse_career_ops_portals_empty():
    assert parse_career_ops_portals("tracked_companies: []") == []
