import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import digest  # noqa: E402

KEY = "sk_test_abc123"
PHP = r"""
putenv('KR_PANEL_LIB=1');
require $argv[1];
$in = json_decode(file_get_contents('php://stdin'), true);
$out = [];
foreach ($in['tokens'] as $t) $out[] = kp_verify($t, $in['key']);
$out[] = kp_keywords(" städ ;fönsterputs,Städ, x ");
echo json_encode($out, JSON_UNESCAPED_UNICODE);
"""


def php(tokens, key=KEY):
    res = subprocess.run(["php", "-r", PHP, str(ROOT / "konto" / "index.php")],
                         input=json.dumps({"tokens": tokens, "key": key}), capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def token(link):
    return link.split("?t=", 1)[1]


class PanelTokenTests(unittest.TestCase):
    def test_digest_link_is_accepted_by_panel(self):
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": KEY, "SITE_URL": "https://kommunradar.online"}):
            good = digest.panel_link("Anna@Firma.se")
            expired = digest.panel_link("anna@firma.se", now=0)
        self.assertTrue(good.startswith("https://kommunradar.online/konto/?t="))
        tampered = token(good)[:-2] + ("AA" if not token(good).endswith("AA") else "BB")
        out = php([token(good), token(expired), tampered, "skräp"])
        self.assertEqual(out[:4], ["anna@firma.se", None, None, None])
        self.assertEqual(out[4], "städ, fönsterputs")

    def test_other_key_is_rejected(self):
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": KEY}):
            link = digest.panel_link("a@b.se")
        self.assertEqual(php([token(link)], key="sk_test_other")[0], None)

    def test_without_key_links_to_login_page(self):
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "", "SITE_URL": ""}):
            self.assertEqual(digest.panel_link("a@b.se"), "https://kommunradar.online/konto/")

    def test_paused_subscription_gets_no_mail(self):
        sub = {"id": "sub_1", "status": "active", "metadata": {"keywords": "städ", "lan": "skane", "paused": "1"},
               "customer": {"email": "a@b.se"}, "items": {"data": [{"price": {"product": "prod_1"}}]}}
        live = {**sub, "id": "sub_2", "metadata": {"keywords": "städ", "lan": "skane"}}

        def fake(path, params=None):
            if path == "subscriptions":
                return {"data": [sub, live] if params["status"] == "active" else [], "has_more": False}
            return {"data": []}
        with mock.patch("digest.kommunradar_products", return_value={"prod_1": "pro"}), mock.patch("digest.stripe_get", fake):
            self.assertEqual(len(list(digest.subscribers())), 1)


if __name__ == "__main__":
    unittest.main()
