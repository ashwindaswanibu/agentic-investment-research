"""Keyless public research APIs, with attributable records and bounded requests.

Official references:
https://clinicaltrials.gov/data-api/api
https://www.ncbi.nlm.nih.gov/books/NBK25499/
Trial completion dates are NOT asserted to be public result/readout dates.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from urllib.parse import urlencode

from .errors import DataError
from .evidence import fetch_json

_NCBI_LOCK = threading.Lock()
_NCBI_LAST_REQUEST = 0.0


def _search_args(query: str, limit: int) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise DataError("invalid_query", "provide a nonempty query of at most 1000 characters")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise DataError("invalid_limit", "search limit must be an integer from 1 to 20")


def _study_record(study: dict) -> dict:
    try:
        identifier = study["protocolSection"]["identificationModule"]["nctId"]
        if not re.fullmatch(r"NCT\d{8}", identifier):
            raise ValueError("invalid trial identifier")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError(
            "clinical_schema_changed", "trial record lacks a valid NCT identifier"
        ) from exc
    return {
        "id": identifier,
        "url": f"https://clinicaltrials.gov/study/{identifier}",
        "record": study,
        "sha256": hashlib.sha256(
            json.dumps(study, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def search_trials(query: str, limit: int = 10) -> dict:
    _search_args(query, limit)
    url = "https://clinicaltrials.gov/api/v2/studies?" + urlencode(
        {"query.term": query, "pageSize": limit, "format": "json", "countTotal": "true"}
    )
    data, provenance = fetch_json(url, allowed_hosts={"clinicaltrials.gov"}, max_bytes=2_000_000)
    studies = data.get("studies")
    if not isinstance(studies, list) or len(studies) > limit:
        raise DataError(
            "clinical_schema_changed", "trial search returned an unexpected record list"
        )
    return {
        "query": query,
        "items": [_study_record(study) for study in studies],
        "total_count": data.get("totalCount"),
        "next_page_token": data.get("nextPageToken"),
        "provenance": provenance,
        "untrusted_source": True,
        "limitations": [
            "Registry records are submitted information and may be revised.",
            "Primary completion dates do not establish when results become public.",
            "Current registry records are not point-in-time historical evidence.",
        ],
    }


def get_trial(nct_id: str) -> dict:
    if not re.fullmatch(r"NCT\d{8}", nct_id):
        raise DataError("invalid_trial_id", "trial identifier must be NCT followed by eight digits")
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}?format=json"
    data, provenance = fetch_json(url, allowed_hosts={"clinicaltrials.gov"}, max_bytes=2_000_000)
    record = _study_record(data)
    if record["id"] != nct_id:
        raise DataError(
            "clinical_identifier_mismatch", "source returned a different trial identifier"
        )
    return {**record, "provenance": provenance, "untrusted_source": True}


def _ncbi_json(url: str) -> tuple[dict, dict]:
    global _NCBI_LAST_REQUEST
    # NCBI keyless policy: no more than three requests/second. Serialize starts
    # within this process; multi-worker deployments still need a shared limiter.
    with _NCBI_LOCK:
        delay = 0.35 - (time.monotonic() - _NCBI_LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
        _NCBI_LAST_REQUEST = time.monotonic()
    return fetch_json(url, allowed_hosts={"eutils.ncbi.nlm.nih.gov"}, max_bytes=1_000_000)


def search_pubmed(query: str, limit: int = 10) -> dict:
    _search_args(query, limit)
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    search_url = (
        base
        + "esearch.fcgi?"
        + urlencode(
            {
                "db": "pubmed",
                "term": query,
                "retmax": limit,
                "retmode": "json",
                "tool": "researchdesk",
            }
        )
    )
    data, search_provenance = _ncbi_json(search_url)
    result = data.get("esearchresult")
    if not isinstance(result, dict) or not isinstance(result.get("idlist"), list):
        raise DataError("pubmed_schema_changed", "PubMed search response lacks an identifier list")
    ids = result["idlist"]
    if len(ids) > limit or any(not isinstance(uid, str) or not uid.isdigit() for uid in ids):
        raise DataError("pubmed_schema_changed", "PubMed returned invalid identifiers")
    provenance, items = [search_provenance], []
    if ids:
        summary_url = (
            base
            + "esummary.fcgi?"
            + urlencode(
                {"db": "pubmed", "id": ",".join(ids), "retmode": "json", "tool": "researchdesk"}
            )
        )
        summaries, summary_provenance = _ncbi_json(summary_url)
        records = summaries.get("result")
        if not isinstance(records, dict):
            raise DataError("pubmed_schema_changed", "PubMed summary response lacks records")
        provenance.append(summary_provenance)
        for uid in ids:
            record = records.get(uid)
            if not isinstance(record, dict) or "error" in record:
                raise DataError(
                    "pubmed_record_missing", "a requested PubMed record was not returned"
                )
            items.append(
                {
                    "id": uid,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "record": record,
                    "sha256": hashlib.sha256(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                }
            )
    return {
        "query": query,
        "items": items,
        "total_count": result.get("count"),
        "provenance": provenance,
        "untrusted_source": True,
        "coverage": "Bibliographic metadata only; review the source for substantive claims.",
    }
