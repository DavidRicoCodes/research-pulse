import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import collector


def snapshot(date, observed, citations):
    return {
        "date": date,
        "sources": {"google_scholar": {
            "observed_at": observed,
            "metrics": {"citations": citations, "papers": 1, "h_index": 1, "i10_index": 1},
        }},
        "papers": [{"title": "Research paper", "year": 2026, "doi": None,
                    "sources": {"google_scholar": citations}}],
    }


class FallbackTests(unittest.TestCase):
    def test_scholar_denial_is_not_retried(self):
        for code in (403, 429):
            with self.subTest(code=code), \
                 patch.object(collector.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("https://scholar.google.com", code, "Denied", {}, None)) as request, \
                 patch.object(collector.time, "sleep") as sleep:
                with self.assertRaises(RuntimeError):
                    collector.get_text("https://scholar.google.com")
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()

    def test_blocked_collection_keeps_newest_observation(self):
        history = {"snapshots": [snapshot("2026-10-03", "2026-10-03", 33),
                                 snapshot("2026-10-05", "2026-09-07", 31)]}
        saved = collector.latest_fallback("google_scholar", history, {})
        self.assertEqual(saved["metrics"]["citations"], 33)
        self.assertEqual(saved["observed_at"], "2026-10-03")
        self.assertEqual(saved["papers"][0]["citations"], 33)

    def test_real_decrease_is_not_replaced_with_historical_maximum(self):
        history = {"snapshots": [snapshot("2026-10-03", "2026-10-03", 33),
                                 snapshot("2026-10-04", "2026-10-04", 32)]}
        self.assertEqual(collector.latest_fallback("google_scholar", history, {})["metrics"]["citations"], 32)

    def test_failed_run_does_not_publish_partial_provider_results(self):
        def partial_failure(ids, papers):
            collector.upsert_paper(papers, title="Incomplete", year=2026, doi=None,
                                   source="semantic_scholar", citations=2)
            raise RuntimeError("Second author request failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            manual = root / "manual.json"
            history = root / "history.json"
            config.write_text(json.dumps({"researcher": {"scholar_id": "test"}}))
            manual.write_text("{}")
            saved = snapshot("2026-10-03", "2026-10-03", 33)
            saved["sources"]["semantic_scholar"] = {"observed_at": "2026-10-03", "metrics": {"papers": 1, "citations": 20}}
            saved["papers"][0]["sources"]["semantic_scholar"] = 20
            history.write_text(json.dumps({"snapshots": [saved]}))
            with patch.multiple(collector, CONFIG_PATH=config, MANUAL_PATH=manual, HISTORY_PATH=history), \
                 patch.object(collector, "collect_google_scholar", side_effect=RuntimeError("403")), \
                 patch.object(collector, "collect_openalex", side_effect=RuntimeError("Offline")), \
                 patch.object(collector, "collect_semantic_scholar", side_effect=partial_failure):
                collector.main()
            result = json.loads(history.read_text())["snapshots"][-1]
            self.assertEqual(result["sources"]["google_scholar"]["metrics"]["citations"], 33)
            self.assertEqual(result["sources"]["semantic_scholar"]["metrics"]["citations"], 20)
            self.assertEqual(result["sources"]["google_scholar"]["observed_at"], "2026-10-03")
            self.assertNotIn("Incomplete", [p["title"] for p in result["papers"]])


if __name__ == "__main__":
    unittest.main()
