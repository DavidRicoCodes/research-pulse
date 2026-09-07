#!/usr/bin/env python3
"""Collect and merge David Rico's public research metrics.

Only Python's standard library is required. OpenAlex profiles are known to be
split, so papers are merged by DOI and then by a normalized title.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MANUAL_PATH = ROOT / "data" / "manual-sources.json"
HISTORY_PATH = ROOT / "data" / "history.json"
USER_AGENT = "DavidRicoResearchDashboard/0.1 (public academic metadata collector)"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def get_json(url: str, retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def get_text(url: str, retries: int = 3) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ResearchPulse/1.0)",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


class ScholarProfileParser(HTMLParser):
    """Extract public totals and the visible publication table from Scholar."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metrics: list[str] = []
        self.papers: list[dict[str, str]] = []
        self._metric_parts: list[str] | None = None
        self._paper: dict[str, str] | None = None
        self._field: str | None = None
        self._field_tag: str | None = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        value = dict(attrs).get("class") or ""
        return set(value.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if tag == "td" and "gsc_rsb_std" in classes:
            self._metric_parts = []
        if tag == "tr" and "gsc_a_tr" in classes:
            self._paper = {"title": "", "citations": "", "year": ""}
        if self._paper is not None:
            if tag == "a" and "gsc_a_at" in classes:
                self._field, self._field_tag = "title", tag
            elif tag == "a" and "gsc_a_ac" in classes:
                self._field, self._field_tag = "citations", tag
            elif tag == "span" and "gsc_a_hc" in classes:
                self._field, self._field_tag = "year", tag

    def handle_data(self, data: str) -> None:
        if self._metric_parts is not None:
            self._metric_parts.append(data)
        if self._paper is not None and self._field:
            self._paper[self._field] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._metric_parts is not None:
            self.metrics.append("".join(self._metric_parts).strip())
            self._metric_parts = None
        if self._field_tag == tag:
            self._field = self._field_tag = None
        if tag == "tr" and self._paper is not None:
            if self._paper["title"].strip():
                self.papers.append({key: value.strip() for key, value in self._paper.items()})
            self._paper = None


def collect_google_scholar(
    scholar_id: str, papers: dict[str, dict[str, Any]], observed_at: str
) -> dict[str, Any]:
    profile_url = (
        "https://scholar.google.com/citations?"
        + urllib.parse.urlencode({"user": scholar_id, "hl": "es"})
    )
    parser = ScholarProfileParser()
    parser.feed(get_text(profile_url))
    if len(parser.metrics) < 5 or not parser.papers:
        raise RuntimeError("Google Scholar returned an incomplete or blocked profile")

    try:
        reported = {
            "papers": len(parser.papers),
            "citations": int(parser.metrics[0]),
            "h_index": int(parser.metrics[2]),
            "i10_index": int(parser.metrics[4]),
        }
    except (ValueError, IndexError) as exc:
        raise RuntimeError("Google Scholar returned unexpected metric values") from exc

    for work in parser.papers:
        upsert_paper(
            papers,
            title=work["title"],
            year=int(work["year"]) if work["year"].isdigit() else None,
            doi=None,
            source="google_scholar",
            citations=int(work["citations"]) if work["citations"].isdigit() else 0,
        )
    return {
        "observed_at": observed_at,
        "profile_url": profile_url,
        "reported_metrics": reported,
    }


def normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def paper_key(title: str, doi: str | None = None) -> str:
    if doi:
        clean_doi = doi.lower().replace("https://doi.org/", "").strip()
        return f"doi:{clean_doi}"
    return f"title:{normalized_title(title)}"


def h_index(citations: list[int]) -> int:
    ordered = sorted(citations, reverse=True)
    return max((rank for rank, count in enumerate(ordered, 1) if count >= rank), default=0)


def upsert_paper(
    papers: dict[str, dict[str, Any]],
    *,
    title: str,
    year: int | None,
    doi: str | None,
    source: str,
    citations: int,
    url: str | None = None,
) -> None:
    key = paper_key(title, doi)
    normalized = normalized_title(title)
    # DOI coverage differs by provider, and a provider may even expose the same
    # work with two IDs. A normalized-title match is therefore always checked.
    if key not in papers:
        for existing_key, item in papers.items():
            if normalized_title(item["title"]) == normalized:
                key = existing_key
                break

    item = papers.setdefault(
        key,
        {"id": key, "title": title, "year": year, "doi": doi, "url": url, "sources": {}},
    )
    item["year"] = item.get("year") or year
    item["doi"] = item.get("doi") or doi
    item["url"] = item.get("url") or url
    # Duplicate author profiles from one provider must not double-count a work.
    item["sources"][source] = max(item["sources"].get(source, 0), citations or 0)


def collect_openalex(ids: list[str], papers: dict[str, dict[str, Any]]) -> None:
    for author_id in ids:
        query = urllib.parse.urlencode(
            {"filter": f"author.id:{author_id}", "per-page": 200, "sort": "publication_date:desc"}
        )
        payload = get_json(f"https://api.openalex.org/works?{query}")
        for work in payload.get("results", []):
            upsert_paper(
                papers,
                title=work.get("display_name") or "Untitled",
                year=work.get("publication_year"),
                doi=work.get("doi"),
                source="openalex",
                citations=work.get("cited_by_count") or 0,
                url=work.get("id"),
            )


def collect_semantic_scholar(ids: list[str], papers: dict[str, dict[str, Any]]) -> None:
    fields = "title,year,citationCount,url,externalIds"
    for author_id in ids:
        payload = get_json(
            f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
            f"?limit=100&fields={urllib.parse.quote(fields)}"
        )
        for work in payload.get("data", []):
            external_ids = work.get("externalIds") or {}
            upsert_paper(
                papers,
                title=work.get("title") or "Untitled",
                year=work.get("year"),
                doi=external_ids.get("DOI"),
                source="semantic_scholar",
                citations=work.get("citationCount") or 0,
                url=work.get("url"),
            )


def add_manual_sources(
    manual: dict[str, Any], papers: dict[str, dict[str, Any]], skip_sources: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    skip_sources = skip_sources or set()
    for source, payload in manual.items():
        if source in skip_sources:
            continue
        metadata[source] = {
            "observed_at": payload.get("observed_at"),
            "profile_url": payload.get("profile_url"),
            "reported_metrics": payload.get("metrics", {}),
        }
        for work in payload.get("papers", []):
            upsert_paper(
                papers,
                title=work["title"],
                year=work.get("year"),
                doi=work.get("doi"),
                source=source,
                citations=work.get("citations") or 0,
            )
    return metadata


def source_metrics(
    source: str, papers: dict[str, dict[str, Any]], reported: dict[str, Any] | None = None
) -> dict[str, int]:
    citations = [item["sources"][source] for item in papers.values() if source in item["sources"]]
    computed = {
        "papers": len(citations),
        "citations": sum(citations),
        "h_index": h_index(citations),
        "i10_index": sum(value >= 10 for value in citations),
    }
    return {**computed, **(reported or {})}


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    researcher = config["researcher"]
    papers: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    now = datetime.now(timezone.utc)
    live_metadata: dict[str, dict[str, Any]] = {}
    try:
        live_metadata["google_scholar"] = collect_google_scholar(
            researcher["scholar_id"], papers, now.date().isoformat()
        )
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        collect_openalex(researcher.get("openalex_ids", []), papers)
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        collect_semantic_scholar(researcher.get("semantic_scholar_ids", []), papers)
    except RuntimeError as exc:
        errors.append(str(exc))

    manual_metadata = add_manual_sources(
        load_json(MANUAL_PATH, {}), papers, skip_sources=set(live_metadata)
    )
    source_metadata = {**manual_metadata, **live_metadata}
    sources: dict[str, Any] = {}
    for source in ("google_scholar", "semantic_scholar", "openalex"):
        metadata = source_metadata.get(source, {})
        available = any(source in paper["sources"] for paper in papers.values())
        if available or metadata:
            sources[source] = {
                "metrics": source_metrics(source, papers, metadata.get("reported_metrics")),
                "observed_at": metadata.get("observed_at"),
                "profile_url": metadata.get("profile_url"),
            }

    snapshot = {
        "date": now.date().isoformat(),
        "collected_at": now.isoformat(timespec="seconds"),
        "researcher": researcher,
        "sources": sources,
        "papers": sorted(papers.values(), key=lambda p: (p.get("year") or 0, p["title"]), reverse=True),
        "warnings": errors,
    }

    history = load_json(HISTORY_PATH, {"schema_version": 1, "snapshots": []})
    snapshots = history.setdefault("snapshots", [])
    snapshots[:] = [item for item in snapshots if item.get("date") != snapshot["date"]]
    snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item["date"])
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Collected {len(papers)} merged papers from {len(sources)} sources "
        f"({len(errors)} warning(s))."
    )
    for warning in errors:
        print(f"WARNING: {warning}", file=sys.stderr)
    return 0 if len(sources) > 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
