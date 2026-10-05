import pytest

from researchdesk.data import DataError, clinical


def test_trial_search_preserves_record_identity_source_and_limit(monkeypatch):
    calls = []
    trial = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Synthetic test record"}
        }
    }

    def get(url, **kwargs):
        calls.append(url)
        return {"studies": [trial], "totalCount": 3, "nextPageToken": "next"}, {
            "sha256": "sourcehash",
            "url": url,
        }

    monkeypatch.setattr(clinical, "fetch_json", get)
    result = clinical.search_trials("phase 3", limit=2)
    assert "pageSize=2" in calls[0]
    assert result["items"][0]["url"] == "https://clinicaltrials.gov/study/NCT01234567"
    assert result["items"][0]["record"] == trial
    assert result["next_page_token"] == "next"
    assert result["provenance"]["sha256"] == "sourcehash"


def test_missing_trial_id_fails_instead_of_manufacturing_citation(monkeypatch):
    monkeypatch.setattr(clinical, "fetch_json", lambda *a, **kw: ({"studies": [{}]}, {}))
    with pytest.raises(DataError) as error:
        clinical.search_trials("query")
    assert error.value.code == "clinical_schema_changed"


def test_pubmed_search_joins_ids_to_exact_metadata(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        if "/esearch.fcgi" in url:
            return {"esearchresult": {"idlist": ["12345"], "count": "10"}}, {"url": url}
        return {"result": {"12345": {"uid": "12345", "title": "Synthetic fixture"}}}, {"url": url}

    monkeypatch.setattr(clinical, "_ncbi_json", get)
    result = clinical.search_pubmed("trial endpoint", 1)
    assert len(calls) == 2
    assert result["items"][0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345/"
    assert len(result["provenance"]) == 2
    assert "metadata only" in result["coverage"]


def test_empty_pubmed_search_is_valid_but_missing_summary_is_not(monkeypatch):
    monkeypatch.setattr(
        clinical, "_ncbi_json", lambda url: ({"esearchresult": {"idlist": [], "count": "0"}}, {})
    )
    assert clinical.search_pubmed("no results")["items"] == []

    def missing(url):
        return (
            {"esearchresult": {"idlist": ["123"], "count": "1"}}
            if "/esearch.fcgi" in url
            else {"result": {}}
        ), {}

    monkeypatch.setattr(clinical, "_ncbi_json", missing)
    with pytest.raises(DataError) as error:
        clinical.search_pubmed("missing summary")
    assert error.value.code == "pubmed_record_missing"
