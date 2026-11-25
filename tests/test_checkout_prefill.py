import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import checkout_prefill_patch as cpp  # noqa: E402

PAGE = """<html><body><!--pp:s-->pris<!--pp:e--><form id="kr-demo-form"></form>
<div id="checkout-note">0 kr idag. Ange dina bevakningsord och välj län i Stripe-kassan.</div>
<script>/*dp:v1*/</script></body></html>"""

LANS = [{"label": "Hela Sverige", "value": "alla"}, {"label": "Skåne", "value": "skane"}]
PRO_LINK = {
    "id": "plink_pro", "url": "https://buy.stripe.com/pro",
    "after_completion": {"type": "redirect", "redirect": {"url": "https://kommunradar.online/tack.html"}},
    "allow_promotion_codes": True, "billing_address_collection": "required",
    "consent_collection": {"terms_of_service": "required"}, "tax_id_collection": {"enabled": True},
    "automatic_tax": {"enabled": False}, "custom_text": {"submit": None},
    "payment_method_collection": "always",
    "custom_fields": [
        {"key": "bevakning", "type": "text", "optional": False, "label": {"type": "custom", "custom": "Bevakningsord"}},
        {"key": "lan", "type": "dropdown", "optional": False, "label": {"type": "custom", "custom": "Län"},
         "dropdown": {"options": LANS}},
    ],
    "metadata": {"app": "kommunradar", "plan": "PRO"},
    "subscription_data": {"metadata": {"plan": "PRO"}, "trial_period_days": 7},
    "restrictions": None,
}
ITEMS = [{"price": {"id": "price_pro", "recurring": {"interval": "month"}}, "quantity": 1}]

PHP = r"""
putenv('KR_CHECKOUT_LIB=1');
require $argv[1];
$in = json_decode(file_get_contents('php://stdin'), true);
$out = [];
foreach ($in['cases'] as $c) {
  if ($c['fn'] === 'county') $out[] = kr_county($c['arg']);
  if ($c['fn'] === 'keywords') $out[] = kr_keywords($c['arg']);
  if ($c['fn'] === 'params') $out[] = kr_session_params($c['link'], $c['items'], $c['values'], 'https://kommunradar.online/');
}
echo json_encode($out, JSON_UNESCAPED_UNICODE);
"""


def php(cases):
    res = subprocess.run(["php", "-r", PHP, str(ROOT / "api" / "checkout.php")], input=json.dumps({"cases": cases}),
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


class PatchTests(unittest.TestCase):
    def test_injects_once_and_is_idempotent(self):
        once = cpp.patch(PAGE, "abc")
        twice = cpp.patch(once, "def")
        self.assertEqual(twice.count("checkout-prefill.js"), 1)
        self.assertIn("?v=def", twice)
        self.assertIn("följer med till kassan", twice)
        self.assertNotIn("i Stripe-kassan", twice)
        self.assertIn("<!--pp:s-->", twice)


@unittest.skipUnless(shutil.which("php"), "php saknas")
class CheckoutPhpTests(unittest.TestCase):
    def test_county_and_keywords(self):
        out = php([
            {"fn": "county", "arg": "Västra Götaland"}, {"fn": "county", "arg": "Hela Sverige"},
            {"fn": "county", "arg": "Skåne län"}, {"fn": "county", "arg": "Narnia"}, {"fn": "county", "arg": ""},
            {"fn": "keywords", "arg": " städ ; fönsterputs,städ, x "},
        ])
        self.assertEqual(out, ["vastragotaland", "alla", "skane", None, None, "städ, fönsterputs"])

    def test_answers_skip_the_questions_and_land_in_metadata(self):
        values = {"keywords": "städ, fönsterputs", "lan": "skane", "email": "anna@firma.se"}
        p = php([{"fn": "params", "link": PRO_LINK, "items": ITEMS, "values": values}])[0]
        self.assertEqual(p["mode"], "subscription")
        self.assertEqual(p["line_items[0][price]"], "price_pro")
        self.assertEqual(p["customer_email"], "anna@firma.se")
        self.assertEqual(p["subscription_data[trial_period_days]"], "7")
        self.assertEqual(p["subscription_data[metadata][keywords]"], "städ, fönsterputs")
        self.assertEqual(p["subscription_data[metadata][lan]"], "skane")
        self.assertEqual(p["subscription_data[metadata][plan]"], "PRO")
        self.assertEqual(p["metadata[payment_link]"], "plink_pro")
        self.assertEqual(p["consent_collection[terms_of_service]"], "required")
        self.assertEqual(p["billing_address_collection"], "required")
        self.assertTrue(p["success_url"].startswith("https://kommunradar.online/tack.html?session_id="))
        self.assertFalse(any(k.startswith("custom_fields") for k in p))

    def test_missing_answer_keeps_that_question(self):
        values = {"keywords": "", "lan": "alla", "email": ""}
        p = php([{"fn": "params", "link": PRO_LINK, "items": ITEMS, "values": values}])[0]
        self.assertEqual(p["custom_fields[0][key]"], "bevakning")
        self.assertNotIn("custom_fields[1][key]", p)
        self.assertNotIn("customer_email", p)
        self.assertNotIn("subscription_data[metadata][keywords]", p)

    def test_one_time_price_uses_payment_mode(self):
        link = dict(PRO_LINK, subscription_data=None)
        items = [{"price": {"id": "price_once", "recurring": None}, "quantity": 1}]
        values = {"keywords": "städ", "lan": "skane", "email": ""}
        p = php([{"fn": "params", "link": link, "items": items, "values": values}])[0]
        self.assertEqual(p["mode"], "payment")
        self.assertEqual(p["payment_intent_data[metadata][keywords]"], "städ")
        self.assertNotIn("payment_method_collection", p)


if __name__ == "__main__":
    unittest.main()
