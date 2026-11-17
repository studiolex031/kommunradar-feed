import io, json, os, shutil, sys, tempfile, unittest
from datetime import date
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import x_daily as xd
import x_mentions as xm


def lead(i, region, cat, pub="2026-11-05", dl="2026-12-01", title=None):
    return {"id": f"{i}-2026", "title": title or f"Upphandling nummer {i}", "buyer": "Testkommun", "region": region,
            "regions": [region], "published": pub, "deadline": dl, "type": "cn-standard", "categories": [cat]}


LEADS = [lead(1, "Skåne", "Bygg & anläggning"), lead(2, "Skåne", "Avfall, städ & miljö"),
         lead(3, "Skåne", "Bygg & anläggning"), lead(4, "Halland", "Bygg & anläggning"),
         lead(5, "Skåne", "IT-tjänster", pub="2026-11-04")]


class XDailyTest(unittest.TestCase):
    def test_even_day_picks_region_from_latest_day_only(self):
        p = xd.pick(LEADS, date.fromordinal(738000))  # jämn
        self.assertEqual((p["kind"], p["focus"], p["n"], p["total"], p["day"]), ("lan", "Skåne", 3, 4, "2026-11-05"))

    def test_odd_day_picks_category(self):
        p = xd.pick(LEADS, date.fromordinal(738001))
        self.assertEqual((p["kind"], p["focus"], p["n"]), ("bransch", "Bygg & anläggning", 3))

    def test_ignores_award_notices_and_handles_empty(self):
        self.assertIsNone(xd.pick([{**LEADS[0], "type": "can-standard"}], date.today()))

    def test_tweet_fits_limit_with_long_titles(self):
        long = [lead(i, "Skåne", "Bygg & anläggning", title="Mycket lång titel " * 8) for i in range(6)]
        text = xd.compose(xd.pick(long, date.fromordinal(738000)), "https://kommunradar.online/?utm_source=x")
        self.assertLessEqual(xd.tweet_length(text), 280)
        self.assertIn("7 dagar gratis", text)
        self.assertIn("6 nya offentliga upphandlingar i Skåne publicerades 5 nov", text)

    def test_tweet_length_weights_like_x(self):
        self.assertEqual(xd.tweet_length("• a… https://kommunradar.online/?utm=x"), 30)
        self.assertEqual(xd.tweet_length("Västra Götaland"), 15)

    def test_card_escapes_titles(self):
        p = xd.pick([lead(1, "Skåne", "Bygg & anläggning", title="<script>x</script>")] * 2, date.fromordinal(738000))
        self.assertNotIn("<script>x", xd.card_html(p, 1200, 675))

    def test_oauth_signature_matches_x_reference(self):
        # Exempel från X:s dokumentation "Creating a signature".
        keys = ("xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE")
        h = xd.oauth_header("POST", "https://api.twitter.com/1.1/statuses/update.json",
                            {"status": "Hello Ladies + Gentlemen, a signed OAuth request!", "include_entities": "true"},
                            keys, nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts=1318622958)
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', h)


class XMentionsTest(unittest.TestCase):
    def test_formats_mentions_with_username_and_link(self):
        lines = xm.format_mentions({"data": [{"id": "9", "author_id": "1", "text": "Funkar det för Gotland?",
                                              "created_at": "2026-11-06T09:12:00.000Z"}],
                                    "includes": {"users": [{"id": "1", "username": "byggare"}]}})
        self.assertEqual(lines, ["@byggare (2026-11-06 09:12):\nFunkar det för Gotland?\nhttps://x.com/byggare/status/9\n"])


    def test_fetch_all_follows_pages_and_keeps_newest_from_first_page(self):
        pages = [{"data": [{"id": "30", "author_id": "1", "text": "a"}], "includes": {"users": [{"id": "1", "username": "u"}]},
                  "meta": {"newest_id": "30", "next_token": "p2"}},
                 {"data": [{"id": "20", "author_id": "1", "text": "b"}], "includes": {"users": [{"id": "1", "username": "u"}]},
                  "meta": {"newest_id": "20"}}]
        seen = []
        def fake(method, url, keys, params=None):
            seen.append(params.get("pagination_token")); return pages[len(seen) - 1]
        lines, newest = xm.fetch_all("9", None, "10", request=fake)
        self.assertEqual((len(lines), newest, seen), (2, "30", [None, "p2"]))


class XAuthTest(unittest.TestCase):
    """Val av auth: OAuth 1.0a om de fyra nycklarna finns, annars OAuth 2.0 med roterande refresh-token."""

    NAMES = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET",
             "X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN", "X_TOKEN_STATE")

    def setUp(self):
        self.saved = {n: os.environ.pop(n) for n in self.NAMES if n in os.environ}
        self.dir = tempfile.mkdtemp()
        os.environ["X_TOKEN_STATE"] = os.path.join(self.dir, "state.json")

    def tearDown(self):
        for n in self.NAMES:
            os.environ.pop(n, None)
        os.environ.update(self.saved)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_oauth1_wins_when_four_keys_exist(self):
        os.environ.update({"X_API_KEY": "ck", "X_API_SECRET": "cs",
                           "X_ACCESS_TOKEN": "tk", "X_ACCESS_SECRET": "ts"})
        auth, reason = xd.x_auth()
        self.assertIsNone(reason)
        self.assertTrue(auth("POST", "https://api.x.com/2/tweets", None)["Authorization"].startswith("OAuth "))

    def test_without_credentials_reports_missing(self):
        self.assertEqual(xd.x_auth(), (None, "X-nycklar saknas"))

    def test_refresh_rotates_token_and_persists_it(self):
        os.environ.update({"X_CLIENT_ID": "cid", "X_CLIENT_SECRET": "csec", "X_REFRESH_TOKEN": "r1"})
        seen = []

        def fake_urlopen(req, timeout=0):
            seen.append({"url": req.full_url, "body": req.data.decode(),
                         "auth": req.headers.get("Authorization")})
            return io.BytesIO(b'{"access_token":"at2","refresh_token":"r2","expires_in":7200,'
                              b'"scope":"tweet.write offline.access"}')

        with mock.patch.object(xd.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(xd.oauth2_token(), ("at2", None))
            # andra körningen ska använda det roterade refresh-tokenet, inte miljövariabeln
            self.assertEqual(xd.oauth2_token(), ("at2", None))

        self.assertEqual(seen[0]["url"], "https://api.x.com/2/oauth2/token")
        self.assertIn("grant_type=refresh_token", seen[0]["body"])
        self.assertIn("refresh_token=r1", seen[0]["body"])
        self.assertTrue(seen[0]["auth"].startswith("Basic "))
        self.assertIn("refresh_token=r2", seen[1]["body"])
        with open(os.environ["X_TOKEN_STATE"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["refresh_token"], "r2")

    def test_uses_stored_token_before_env(self):
        os.environ.update({"X_CLIENT_ID": "cid", "X_REFRESH_TOKEN": "old"})
        with open(os.environ["X_TOKEN_STATE"], "w", encoding="utf-8") as f:
            json.dump({"refresh_token": "stored"}, f)
        bodies = []
        with mock.patch.object(xd.urllib.request, "urlopen",
                               lambda req, timeout=0: bodies.append(req.data.decode())
                               or io.BytesIO(b'{"access_token":"a","refresh_token":"b"}')):
            xd.oauth2_token()
        self.assertIn("refresh_token=stored", bodies[0])


if __name__ == "__main__":
    unittest.main()
