"""API test script.

Tests all endpoints and parameters. Run with API server running:

  python test/test_api.py
  python test/test_api.py --base-url http://210.45.70.162:4000
  python test/test_api.py --save-json test/api_responses.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

PASS = "✅"
FAIL = "❌"

# Collect API responses for JSON output.
_responses: dict = {}


def _get(
    url: str,
    params: dict | None = None,
    timeout: int = 60,
    save_as: str | None = None,
) -> tuple[bool, str, int]:
    """GET request. Returns (success, message, status_code). Optionally saves response."""
    try:
        r = requests.get(url, params=params, timeout=timeout)
        data = None
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()
            except json.JSONDecodeError:
                pass
        if save_as:
            _responses[save_as] = {
                "url": url,
                "params": params,
                "status_code": r.status_code,
                "response": data if data is not None else r.text[:500],
            }
        if r.status_code == 200:
            if isinstance(data, dict) and "data" in data:
                return True, f"OK (total={data.get('total', len(data['data']))})", r.status_code
            return True, "OK", r.status_code
        return False, f"status={r.status_code} {r.text[:100]}", r.status_code
    except requests.RequestException as e:
        if save_as:
            _responses[save_as] = {"url": url, "params": params, "error": str(e)}
        return False, str(e), 0


def _test(name: str, ok: bool, msg: str) -> bool:
    """Print and return."""
    symbol = PASS if ok else FAIL
    print(f"  {symbol} {name}: {msg}")
    return ok


SEARCH_QUERY = "TimeDART time series diffusion"


def test_search(base: str) -> bool:
    """GET /paper/search."""
    print("\n--- GET /paper/search ---")
    all_ok = True

    # Basic
    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY}, save_as="search_query")
    all_ok &= _test(f"query={SEARCH_QUERY!r}", ok, msg)

    # retrieval modes
    for mode in ("sparse", "dense", "hybrid"):
        ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "retrieval": mode}, save_as=f"search_retrieval_{mode}")
        all_ok &= _test(f"retrieval={mode}", ok, msg)

    # filters
    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "year": "2020"}, save_as="search_year_2020")
    all_ok &= _test("year=2020", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "year": "2018-2022"}, save_as="search_year_range")
    all_ok &= _test("year=2018-2022", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "minCitationCount": 10}, save_as="search_min_citations")
    all_ok &= _test("minCitationCount=10", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "openAccessPdf": "1"}, save_as="search_open_access")
    all_ok &= _test("openAccessPdf", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "venue": "NeurIPS"}, save_as="search_venue")
    all_ok &= _test("venue=NeurIPS", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "fieldsOfStudy": "Computer Science"}, save_as="search_fields_of_study")
    all_ok &= _test("fieldsOfStudy", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "publicationTypes": "JournalArticle"}, save_as="search_publication_types")
    all_ok &= _test("publicationTypes", ok, msg)

    # pagination
    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "limit": 5, "offset": 2}, save_as="search_pagination")
    all_ok &= _test("limit=5, offset=2", ok, msg)

    # fields
    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "fields": "abstract,year"}, save_as="search_fields")
    all_ok &= _test("fields=abstract,year", ok, msg)

    # fields=* returns all metadata
    ok, msg, _ = _get(f"{base}/paper/search", {"query": SEARCH_QUERY, "fields": "*", "limit": 1}, save_as="search_fields_all")
    all_ok &= _test("fields=* (all metadata)", ok, msg)

    return all_ok


def test_search_title(base: str) -> bool:
    """GET /paper/search/title."""
    print("\n--- GET /paper/search/title ---")
    all_ok = True

    ok, msg, _ = _get(f"{base}/paper/search/title", {"query": "TimeDART", "limit": 5}, save_as="search_title_timedart")
    all_ok &= _test("query=TimeDART", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search/title", {"query": "TimeDART", "year": "2024"}, save_as="search_title_year")
    all_ok &= _test("year=2024", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/search/title", {"query": "TimeDART", "fields": "abstract"}, save_as="search_title_fields")
    all_ok &= _test("fields=abstract", ok, msg)

    return all_ok


def test_paper_detail(base: str, sample_paper_id: str) -> bool:
    """GET /paper/{paper_id}."""
    print("\n--- GET /paper/{paper_id} ---")
    all_ok = True

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}", save_as="paper_detail")
    all_ok &= _test("SHA (paper_id)", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}", {"fields": "abstract,year,authors"}, save_as="paper_detail_fields")
    all_ok &= _test("fields=abstract,year,authors", ok, msg)

    ok, msg, code = _get(f"{base}/paper/nonexistent123456", save_as="paper_detail_404")
    all_ok &= _test("404 for nonexistent", not ok and code == 404, msg)

    return all_ok


def test_citations(base: str, sample_paper_id: str) -> bool:
    """GET /paper/{paper_id}/citations."""
    print("\n--- GET /paper/{paper_id}/citations ---")
    all_ok = True

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}/citations", save_as="citations")
    all_ok &= _test("default", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}/citations", {"limit": 3, "offset": 1}, save_as="citations_pagination")
    all_ok &= _test("limit=3, offset=1", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}/citations", {"fields": "title,year"}, save_as="citations_fields")
    all_ok &= _test("fields=title,year", ok, msg)

    return all_ok


def test_references(base: str, sample_paper_id: str) -> bool:
    """GET /paper/{paper_id}/references."""
    print("\n--- GET /paper/{paper_id}/references ---")
    all_ok = True

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}/references", save_as="references")
    all_ok &= _test("default", ok, msg)

    ok, msg, _ = _get(f"{base}/paper/{sample_paper_id}/references", {"limit": 5}, save_as="references_limit")
    all_ok &= _test("limit=5", ok, msg)

    return all_ok


SAMPLE_PAPER_QUERY = "TimeDART: A Diffusion Autoregressive Transformer for Self-Supervised Time-Series Representations"


def get_sample_paper_id(base: str, sample_query: str | None = None) -> str | None:
    """Get paper_id for TimeDART via title search.

    Tries full title first, then "TimeDART" as fallback (FTS5 may not match long phrases).
    Use sample_query to override (e.g. if TimeDART not in corpus).
    """
    query_list = [sample_query or SAMPLE_PAPER_QUERY, "TimeDART"] if sample_query is None else [sample_query]
    for query in query_list:
        ok, _, _ = _get(
            f"{base}/paper/search/title",
            params={"query": query, "limit": 10},
            timeout=30,
            save_as="sample_paper_search",
        )
        if ok and "sample_paper_search" in _responses:
            data = _responses["sample_paper_search"].get("response")
            if isinstance(data, dict) and data.get("data"):
                for item in data["data"]:
                    title = (item.get("title") or "").lower()
                    if sample_query:
                        return item.get("paperId")  # Use first result when user specifies query
                    if "timedart" in title:
                        return item.get("paperId")
    return None


def run_tests(base_url: str, save_json: str | None = None, sample_query: str | None = None) -> bool:
    """Run all tests. Returns True if all pass."""
    global _responses
    _responses = {}

    print("=" * 60)
    print(f"Paper Search API Test — {base_url}")
    print("=" * 60)

    # Health check via real API
    try:
        r = requests.get(f"{base_url}/paper/search", params={"query": "test", "limit": 1}, timeout=10)
        if r.status_code != 200:
            print(f"{FAIL} API not ready: {base_url} (status={r.status_code})")
            return False
    except requests.RequestException as e:
        print(f"{FAIL} Server not reachable: {e}")
        print("  Start the API first: python main.py")
        return False

    print(f"{PASS} API reachable")

    all_ok = True
    all_ok &= test_search(base_url)
    all_ok &= test_search_title(base_url)

    sample_query_used = sample_query or SAMPLE_PAPER_QUERY
    sample_id = get_sample_paper_id(base_url, sample_query)
    _responses["_metadata"] = {
        "base_url": base_url,
        "sample_paper_query": sample_query_used,
        "sample_paper_id": sample_id,
    }
    if sample_id:
        print(f"\n📋 Sample paper: {sample_query_used[:50]}...")
        print(f"   paper_id: {sample_id[:16]}...")
        all_ok &= test_paper_detail(base_url, sample_id)
        all_ok &= test_citations(base_url, sample_id)
        all_ok &= test_references(base_url, sample_id)
    else:
        print("\n--- GET /paper/{id}, /citations, /references ---")
        print(f"  {FAIL} Skipped: '{sample_query_used[:50]}...' not found")
        all_ok = False

    if save_json:
        out_path = Path(save_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Put _metadata first for readability
        output = {"_metadata": _responses.pop("_metadata", {})}
        output.update(_responses)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n📁 API responses saved to {out_path}")

    print("\n" + "=" * 60)
    print(f"{PASS} All tests passed" if all_ok else f"{FAIL} Some tests failed")
    print("=" * 60)
    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test all Paper Search API endpoints")
    parser.add_argument(
        "--base-url",
        default="http://localhost:4000",
        help="API base URL (e.g. http://210.45.70.162:4000)",
    )
    parser.add_argument(
        "--save-json",
        default="test/api_responses.json",
        metavar="FILE",
        help="Save API responses to JSON file (default: test/api_responses.json)",
    )
    parser.add_argument(
        "--sample-query",
        default=None,
        metavar="QUERY",
        help="Override sample paper query if TimeDART not in corpus (e.g. 'Attention is all you need')",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    success = run_tests(base, save_json=args.save_json, sample_query=args.sample_query)
    sys.exit(0 if success else 1)
