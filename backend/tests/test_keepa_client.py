"""Tests for backend/keepa_client.py using httpx.MockTransport.

No real network calls and no real Keepa API key are used anywhere here —
every HTTP response is fabricated by a MockTransport handler.
"""

import os
import sys
import time
import unittest
from unittest import mock

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import keepa_client  # noqa: E402

FAKE_KEY = "test-fake-keepa-key"


def keepa_minutes(days_ago: float = 0) -> int:
    """Keepa Time (minutes) for a point `days_ago` days before now."""
    unix_seconds = time.time() - days_ago * 86400
    return int(unix_seconds / 60) - keepa_client.KEEPA_EPOCH_OFFSET_MIN


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def full_product(**overrides) -> dict:
    """A well-formed Keepa product with all four CSV series populated,
    all points recent enough (within 30 days) to land in every avg window."""
    csv = [None] * 19
    csv[keepa_client.CSV_AMAZON] = [keepa_minutes(5), 1999, keepa_minutes(1), 2099]
    csv[keepa_client.CSV_NEW] = [keepa_minutes(5), 1899, keepa_minutes(1), 1999]
    csv[keepa_client.CSV_SALES_RANK] = [keepa_minutes(5), 15000, keepa_minutes(1), 12000]
    csv[keepa_client.CSV_BUY_BOX] = [keepa_minutes(5), 1950, keepa_minutes(1), 2050]
    product = {
        "asin": "B0EXAMPLE1",
        "title": "Widget XYZ",
        "brand": "Acme",
        "categoryTree": [{"name": "Home"}, {"name": "Kitchen"}],
        "csv": csv,
    }
    product.update(overrides)
    return product


class SuccessfulResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_populates_all_fields(self):
        def handler(request):
            return json_response({"tokensLeft": 42, "products": [full_product()]})

        client = make_client(handler)
        result = await keepa_client.fetch_keepa_product("B0EXAMPLE1", api_key=FAKE_KEY, client=client)

        self.assertEqual(result.status, keepa_client.KeepaStatus.SUCCESS)
        self.assertIsNone(result.error)
        self.assertEqual(result.asin, "B0EXAMPLE1")
        self.assertEqual(result.domain, "US")
        self.assertEqual(result.domain_code, 1)
        self.assertEqual(result.title, "Widget XYZ")
        self.assertEqual(result.brand, "Acme")
        self.assertEqual(result.category_tree, ["Home", "Kitchen"])
        self.assertEqual(result.current_amazon_price, 20.99)
        self.assertEqual(result.current_new_price, 19.99)
        self.assertEqual(result.current_buy_box_price, 20.50)
        self.assertEqual(result.current_bsr, 12000)
        self.assertEqual(result.tokens_left, 42)
        self.assertEqual(len(result.price_history), 2)
        self.assertEqual(len(result.bsr_history), 2)
        self.assertEqual(len(result.buy_box_history), 2)
        self.assertEqual(result.warnings, [])

    async def test_price_history_prefers_amazon_over_new(self):
        def handler(request):
            return json_response({"products": [full_product()]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        # price_history/avg_price_* should be derived from the Amazon series,
        # not the New series, whenever Amazon history exists.
        self.assertEqual(result.current_amazon_price, result.price_history[-1].value)

    async def test_avg_price_and_bsr_computed_over_window(self):
        def handler(request):
            return json_response({"products": [full_product()]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        # Both points are within 30 days, so avg_price_30 is their mean.
        self.assertAlmostEqual(result.avg_price_30, round((19.99 + 20.99) / 2, 2))
        self.assertEqual(result.avg_bsr_30, round((15000 + 12000) / 2))


class MissingFieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_csv_key_entirely(self):
        product = full_product()
        del product["csv"]

        def handler(request):
            return json_response({"products": [product]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.SUCCESS)
        self.assertIsNone(result.current_amazon_price)
        self.assertIsNone(result.current_bsr)
        self.assertIsNone(result.current_buy_box_price)
        self.assertEqual(result.price_history, [])
        self.assertTrue(any("csv" in w for w in result.warnings))

    async def test_missing_price_series(self):
        product = full_product()
        product["csv"][keepa_client.CSV_AMAZON] = None
        product["csv"][keepa_client.CSV_NEW] = None

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertIsNone(result.current_amazon_price)
        self.assertIsNone(result.current_new_price)
        self.assertEqual(result.avg_price_30, None)
        self.assertTrue(any("price history" in w for w in result.warnings))
        # BSR/Buy Box are unaffected — missing one series doesn't null the others.
        self.assertIsNotNone(result.current_bsr)
        self.assertIsNotNone(result.current_buy_box_price)

    async def test_missing_bsr_series(self):
        product = full_product()
        product["csv"][keepa_client.CSV_SALES_RANK] = None

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertIsNone(result.current_bsr)
        self.assertIsNone(result.avg_bsr_30)
        self.assertIsNone(result.avg_bsr_90)
        self.assertIsNone(result.avg_bsr_180)
        self.assertTrue(any("BSR" in w for w in result.warnings))
        # Price/Buy Box are unaffected.
        self.assertIsNotNone(result.current_amazon_price)

    async def test_missing_buy_box_series(self):
        product = full_product()
        product["csv"][keepa_client.CSV_BUY_BOX] = None

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertIsNone(result.current_buy_box_price)
        self.assertEqual(result.buy_box_history, [])
        self.assertTrue(any("Buy Box" in w for w in result.warnings))
        self.assertIsNotNone(result.current_amazon_price)


class MarketplaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_domain_is_us(self):
        seen = {}

        def handler(request):
            seen["domain"] = request.url.params.get("domain")
            return json_response({"products": [full_product()]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.domain_code, 1)
        self.assertEqual(seen["domain"], "1")

    async def test_gb_and_de_domains_map_to_correct_codes(self):
        for label, expected_code in [("GB", 3), ("DE", 4), ("mx", 11)]:
            seen = {}

            def handler(request, seen=seen):
                seen["domain"] = request.url.params.get("domain")
                return json_response({"products": [full_product()]})

            result = await keepa_client.fetch_keepa_product(
                "B0EXAMPLE1", domain=label, api_key=FAKE_KEY, client=make_client(handler))
            self.assertEqual(result.domain_code, expected_code)
            self.assertEqual(seen["domain"], str(expected_code))
            self.assertEqual(result.domain, label.upper())

    async def test_unknown_domain_rejected(self):
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", domain="ZZ", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [full_product()]})))
        self.assertEqual(result.status, keepa_client.KeepaStatus.INVALID_DOMAIN)
        self.assertIsNone(result.current_amazon_price)


class MalformedResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_json_body(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.MALFORMED_RESPONSE)

    async def test_json_but_not_an_object(self):
        def handler(request):
            return json_response([1, 2, 3])  # type: ignore[arg-type]

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.MALFORMED_RESPONSE)

    async def test_products_not_a_list(self):
        def handler(request):
            return json_response({"products": "not-a-list"})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.NOT_FOUND)

    async def test_products_empty_list(self):
        def handler(request):
            return json_response({"products": []})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.NOT_FOUND)

    async def test_product_entry_not_an_object(self):
        def handler(request):
            return json_response({"products": ["garbage"]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.MALFORMED_RESPONSE)

    async def test_keepa_error_field(self):
        def handler(request):
            return json_response({"error": "Invalid API key"})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.KEEPA_ERROR)
        self.assertIn("Invalid API key", result.error)

    async def test_http_error_status(self):
        def handler(request):
            return httpx.Response(403, text="Forbidden")

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.HTTP_ERROR)
        self.assertIn("403", result.error)


class NetworkFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_error(self):
        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.NETWORK_ERROR)

    async def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out", request=request)

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.NETWORK_ERROR)


class CredentialAndInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_api_key_param_and_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = await keepa_client.fetch_keepa_product("B0EXAMPLE1")
        self.assertEqual(result.status, keepa_client.KeepaStatus.MISSING_API_KEY)

    async def test_env_var_used_when_no_param_given(self):
        def handler(request):
            self.assertEqual(request.url.params.get("key"), "env-key-value")
            return json_response({"products": [full_product()]})

        with mock.patch.dict(os.environ, {"KEEPA_API_KEY": "env-key-value"}):
            result = await keepa_client.fetch_keepa_product("B0EXAMPLE1", client=make_client(handler))
        self.assertEqual(result.status, keepa_client.KeepaStatus.SUCCESS)

    async def test_invalid_asin_empty_string(self):
        result = await keepa_client.fetch_keepa_product("", api_key=FAKE_KEY)
        self.assertEqual(result.status, keepa_client.KeepaStatus.INVALID_ASIN)

    async def test_invalid_asin_non_string(self):
        result = await keepa_client.fetch_keepa_product(None, api_key=FAKE_KEY)  # type: ignore[arg-type]
        self.assertEqual(result.status, keepa_client.KeepaStatus.INVALID_ASIN)


class QuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_tokens_left_missing(self):
        def handler(request):
            return json_response({"products": [full_product()]})  # no tokensLeft key

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertIsNone(result.tokens_left)

    async def test_tokens_left_present(self):
        def handler(request):
            return json_response({"tokensLeft": 7, "products": [full_product()]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertEqual(result.tokens_left, 7)

    async def test_tokens_left_wrong_type_ignored(self):
        def handler(request):
            return json_response({"tokensLeft": "not-a-number", "products": [full_product()]})

        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY, client=make_client(handler))
        self.assertIsNone(result.tokens_left)


class PriceConversionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cents_to_dollars_conversion(self):
        product = full_product()
        product["csv"][keepa_client.CSV_AMAZON] = [keepa_minutes(1), 1999]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(result.current_amazon_price, 19.99)

    async def test_bsr_is_not_divided_by_100(self):
        product = full_product()
        product["csv"][keepa_client.CSV_SALES_RANK] = [keepa_minutes(1), 123456]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(result.current_bsr, 123456)


class SpecialAndMissingValueTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_sentinel_minus_one_is_dropped(self):
        product = full_product()
        product["csv"][keepa_client.CSV_AMAZON] = [
            keepa_minutes(10), -1,             # sentinel: no data — must be dropped
            keepa_minutes(1), 2500,
        ]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(len(result.amazon_price_history), 1)
        self.assertEqual(result.current_amazon_price, 25.00)

    async def test_null_value_in_series_is_dropped(self):
        product = full_product()
        product["csv"][keepa_client.CSV_AMAZON] = [
            keepa_minutes(10), None,
            keepa_minutes(1), 2500,
        ]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(len(result.amazon_price_history), 1)

    async def test_genuine_zero_is_preserved_not_treated_as_missing(self):
        product = full_product()
        # A real $0.00 price point (e.g. a free promo) must survive distinctly
        # from a dropped -1/None sentinel.
        product["csv"][keepa_client.CSV_AMAZON] = [keepa_minutes(1), 0]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(len(result.amazon_price_history), 1)
        self.assertEqual(result.current_amazon_price, 0.0)
        self.assertIsNotNone(result.current_amazon_price)  # not None, not dropped

    async def test_zero_bsr_preserved(self):
        product = full_product()
        product["csv"][keepa_client.CSV_SALES_RANK] = [keepa_minutes(1), 0]
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(result.current_bsr, 0)

    async def test_non_list_csv_series_entry_ignored_gracefully(self):
        product = full_product()
        product["csv"][keepa_client.CSV_AMAZON] = "not-a-list"
        result = await keepa_client.fetch_keepa_product(
            "B0EXAMPLE1", api_key=FAKE_KEY,
            client=make_client(lambda r: json_response({"products": [product]})))
        self.assertEqual(result.status, keepa_client.KeepaStatus.SUCCESS)
        self.assertEqual(result.amazon_price_history, [])


if __name__ == "__main__":
    unittest.main()
