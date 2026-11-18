import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "api" / "create-checkout-session.py"
SPEC = importlib.util.spec_from_file_location("kommunradar_checkout", MODULE_PATH)
checkout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkout)


class CheckoutInputTests(unittest.TestCase):
    def test_normalizes_swedish_county_label(self):
        result = checkout.normalize_checkout_input({
            "keywords": " städ, fönsterputs ; IT-konsult ",
            "lan": "Västra Götaland",
        })
        self.assertEqual(result, {
            "keywords": "städ, fönsterputs, IT-konsult",
            "lan": "vastragotaland",
        })

    def test_empty_search_defaults_to_all_sweden(self):
        self.assertEqual(
            checkout.normalize_checkout_input({"keywords": "", "lan": ""}),
            {"keywords": "", "lan": "alla"},
        )

    def test_rejects_unknown_county(self):
        with self.assertRaises(ValueError):
            checkout.normalize_checkout_input({"keywords": "städ", "lan": "Narnia"})

    def test_rejects_too_many_keywords(self):
        with self.assertRaises(ValueError):
            checkout.normalize_checkout_input({
                "keywords": ", ".join("ord" + str(i) for i in range(9)),
                "lan": "Stockholm",
            })

    def test_rejects_oversized_keyword_input(self):
        with self.assertRaises(ValueError):
            checkout.normalize_checkout_input({"keywords": "x" * 201, "lan": "Stockholm"})

    def test_session_keeps_existing_commercial_terms_and_metadata_contract(self):
        params = checkout.build_session_params(
            "price_test",
            {"keywords": "städ, fönsterputs", "lan": "stockholm"},
            checkout.SITE_ORIGIN,
        )
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(params["subscription_data[trial_period_days]"], "7")
        self.assertEqual(params["billing_address_collection"], "required")
        self.assertEqual(params["payment_method_collection"], "always")
        self.assertEqual(params["subscription_data[metadata][keywords]"], "städ, fönsterputs")
        self.assertEqual(params["subscription_data[metadata][lan]"], "stockholm")
        self.assertEqual(params["consent_collection[terms_of_service]"], "required")
        self.assertEqual(params["tax_id_collection[enabled]"], "true")
        self.assertEqual(params["tax_id_collection[required]"], "never")
        self.assertNotIn("custom_fields[0][key]", params)
        self.assertNotIn("custom_fields[1][key]", params)


if __name__ == "__main__":
    unittest.main()
