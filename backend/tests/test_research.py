"""Tests for backend/research.py using mocked WebSearch/WebFetch-shaped payloads.

No network calls are made anywhere in this file, and nothing here touches
amazon.com — Amazon-specific handling is tested only via the deliberate
"refuse to process amazon.* URLs" guard, not by pretending to fetch real
Amazon data.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import research  # noqa: E402


def make_storage(tmp_dir: str) -> research.ResearchStorage:
    return research.ResearchStorage(
        cache_dir=Path(tmp_dir) / "cache",
        log_path=Path(tmp_dir) / "logs" / "research.log",
    )


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = make_storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_raw_results_returns_not_provided(self):
        result = research.web_search("widget xyz price", storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.NOT_PROVIDED)
        self.assertEqual(result.hits, [])
        self.assertTrue(Path(result.cache_path).exists())

    def test_empty_results_returns_empty_status(self):
        result = research.web_search("a query with no hits", raw_results=[], storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.EMPTY)

    def test_success_normalizes_hits_and_flexible_keys(self):
        raw = [
            {"title": "Widget XYZ - RetailerA", "url": "https://retailera.example.com/p/1",
             "snippet": "Buy Widget XYZ for $19.99 today."},
            {"title": "Widget XYZ - RetailerB", "link": "https://retailerb.example.com/p/2",
             "description": "Widget XYZ, on sale $17.50."},
        ]
        result = research.web_search("widget xyz", raw_results=raw, storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(len(result.hits), 2)
        self.assertEqual(result.hits[0].domain, "retailera.example.com")
        self.assertEqual(result.hits[1].url, "https://retailerb.example.com/p/2")

    def test_tool_error_timeout_classified(self):
        result = research.web_search("slow query", error="Request timed out", storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.TIMEOUT)

    def test_writes_log_entry(self):
        research.web_search("logged query", raw_results=[], storage=self.storage)
        log_lines = self.storage.log_path.read_text().strip().splitlines()
        self.assertEqual(len(log_lines), 1)
        entry = json.loads(log_lines[0])
        self.assertEqual(entry["function"], "web_search")
        self.assertEqual(entry["status"], "empty")


class WebFetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = make_storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_url_rejected(self):
        result = research.web_fetch("not-a-url", storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.INVALID_URL)

    def test_invalid_scheme_rejected(self):
        result = research.web_fetch("ftp://example.com/page", storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.INVALID_URL)

    def test_amazon_domain_refused_even_with_content(self):
        result = research.web_fetch(
            "https://www.amazon.com/dp/B0EXAMPLE1",
            raw_content='{"price": 19.99, "title": "Should be ignored"}',
            storage=self.storage,
        )
        self.assertEqual(result.status, research.RetrievalStatus.UNSUPPORTED_SOURCE)
        self.assertEqual(result.extracted_fields, {})
        self.assertIn("Keepa", result.source.error)

    def test_no_raw_content_returns_not_provided(self):
        result = research.web_fetch("https://retailera.example.com/p/1", storage=self.storage)
        self.assertEqual(result.status, research.RetrievalStatus.NOT_PROVIDED)

    def test_blocked_page_detected(self):
        result = research.web_fetch(
            "https://retailera.example.com/p/1",
            raw_content="Please complete this CAPTCHA to continue. Access denied.",
            storage=self.storage,
        )
        self.assertEqual(result.status, research.RetrievalStatus.BLOCKED)
        self.assertEqual(result.extracted_fields, {})

    def test_json_block_extracted_and_marked_verified(self):
        content = (
            "Here is the product data you asked for:\n"
            '```json\n{"title": "Widget XYZ", "brand": "Acme", "price": 19.99, '
            '"sale_price": 15.99, "availability": "In Stock"}\n```'
        )
        result = research.web_fetch(
            "https://retailera.example.com/p/1", raw_content=content, storage=self.storage,
        )
        self.assertEqual(result.status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(result.extracted_fields["price"], 19.99)
        self.assertEqual(result.field_confidence["price"], research.ConfidenceLabel.VERIFIED)

    def test_plain_text_price_regex_fallback(self):
        result = research.web_fetch(
            "https://retailera.example.com/p/1",
            raw_content="This item is currently priced at $24.50 with free shipping.",
            storage=self.storage,
        )
        self.assertEqual(result.status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(result.extracted_fields["price"], 24.50)

    def test_no_extractable_data_warns_but_succeeds(self):
        result = research.web_fetch(
            "https://retailera.example.com/p/1",
            raw_content="This page has no price information on it at all.",
            storage=self.storage,
        )
        self.assertEqual(result.status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(result.extracted_fields, {})
        self.assertTrue(any("could not be extracted" in w for w in result.warnings))


class ResearchProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = make_storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_inputs_returns_not_provided(self):
        result = research.research_product("widget xyz", storage=self.storage)
        self.assertEqual(result.overall_status, research.RetrievalStatus.NOT_PROVIDED)

    def test_merges_fetched_page_into_product_and_pricing(self):
        fetched = [{
            "url": "https://retailera.example.com/p/1",
            "content": '{"title": "Widget XYZ", "brand": "Acme", "price": 19.99}',
        }]
        result = research.research_product("widget xyz", fetched_pages=fetched, storage=self.storage)
        self.assertEqual(result.overall_status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(result.product.title, "Widget XYZ")
        self.assertEqual(result.product.brand, "Acme")
        self.assertEqual(result.product.field_confidence["title"], research.ConfidenceLabel.VERIFIED)
        self.assertEqual(len(result.pricing), 1)
        self.assertEqual(result.pricing[0].price, 19.99)

    def test_conflicting_prices_across_sources_are_flagged_not_resolved(self):
        fetched = [
            {"url": "https://retailera.example.com/p/1", "content": '{"price": 19.99}'},
            {"url": "https://retailerb.example.com/p/2", "content": '{"price": 24.99}'},
        ]
        result = research.research_product("widget xyz", fetched_pages=fetched, storage=self.storage)
        self.assertEqual(len(result.pricing), 2)
        self.assertTrue(any("Price conflict" in c for c in result.conflicts))
        prices = sorted(p.price for p in result.pricing)
        self.assertEqual(prices, [19.99, 24.99])

    def test_amazon_url_in_fetched_pages_is_refused(self):
        fetched = [{"url": "https://www.amazon.com/dp/B0EXAMPLE1", "content": '{"price": 9.99}'}]
        result = research.research_product("widget xyz", fetched_pages=fetched, storage=self.storage)
        self.assertEqual(result.pricing, [])
        self.assertEqual(result.sources[0].status, research.RetrievalStatus.UNSUPPORTED_SOURCE)

    def test_search_only_prices_marked_estimated_not_verified(self):
        search_results = [
            {"title": "Widget XYZ", "url": "https://retailera.example.com/p/1",
             "snippet": "On sale now for $12.00."},
        ]
        result = research.research_product("widget xyz", search_results=search_results,
                                            storage=self.storage)
        self.assertEqual(len(result.pricing), 1)
        self.assertEqual(result.pricing[0].confidence, research.ConfidenceLabel.ESTIMATED)


class ResearchRetailerProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = make_storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_wraps_single_url_through_research_product(self):
        result = research.research_retailer_product(
            "https://retailera.example.com/p/1",
            raw_content='{"title": "Widget XYZ", "price": 19.99}',
            storage=self.storage,
        )
        self.assertEqual(result.overall_status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(result.pricing[0].price, 19.99)


class ResearchMultipleSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = make_storage(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_sources_returns_not_provided(self):
        result = research.research_multiple_sources("brand x gating", [], storage=self.storage)
        self.assertEqual(result.overall_status, research.RetrievalStatus.NOT_PROVIDED)

    def test_agreeing_fetch_sources_produce_verified_findings(self):
        sources = [
            {"type": "fetch", "input": "https://retailera.example.com/policy",
             "raw": '{"gating_status": "not gated"}', "label": "gating_status"},
        ]
        result = research.research_multiple_sources("brand x gating", sources, storage=self.storage)
        self.assertEqual(result.overall_status, research.RetrievalStatus.SUCCESS)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].confidence, research.ConfidenceLabel.VERIFIED)

    def test_conflicting_findings_flagged(self):
        sources = [
            {"type": "fetch", "input": "https://retailera.example.com/policy",
             "raw": '{"gating_status": "gated"}', "label": "gating_status"},
            {"type": "fetch", "input": "https://retailerb.example.com/policy",
             "raw": '{"gating_status": "not gated"}', "label": "gating_status"},
        ]
        result = research.research_multiple_sources("brand x gating", sources, storage=self.storage)
        self.assertTrue(any("Conflicting values" in c for c in result.conflicts))
        self.assertTrue(all(f.confidence == research.ConfidenceLabel.CONFLICTING for f in result.findings))

    def test_unknown_source_type_warns_and_is_skipped(self):
        sources = [{"type": "carrier-pigeon", "input": "x", "raw": None}]
        result = research.research_multiple_sources("edge case", sources, storage=self.storage)
        self.assertTrue(any("Unknown source type" in w for w in result.warnings))
        self.assertEqual(result.findings, [])


class HelperTests(unittest.TestCase):
    def test_validate_url(self):
        self.assertIsNone(research.validate_url("https://example.com/page"))
        self.assertIsNotNone(research.validate_url("example.com/page"))
        self.assertIsNotNone(research.validate_url(""))

    def test_is_amazon_domain(self):
        self.assertTrue(research.is_amazon_domain("https://www.amazon.com/dp/B0EXAMPLE1"))
        self.assertTrue(research.is_amazon_domain("https://amazon.co.uk/dp/B0EXAMPLE1"))
        self.assertFalse(research.is_amazon_domain("https://not-amazon.com/dp/B0EXAMPLE1"))

    def test_cache_files_are_organized_by_slug_and_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = make_storage(tmp)
            research.web_search("Some Product Name!", raw_results=[], storage=storage)
            slugs = list((Path(tmp) / "cache").iterdir())
            self.assertEqual(len(slugs), 1)
            self.assertEqual(slugs[0].name, "some-product-name")
            cached_files = list(slugs[0].iterdir())
            self.assertEqual(len(cached_files), 1)
            self.assertTrue(cached_files[0].name.endswith("__01.json"))


if __name__ == "__main__":
    unittest.main()
