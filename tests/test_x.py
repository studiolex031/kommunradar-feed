import os, sys, unittest
from datetime import date
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


if __name__ == "__main__":
    unittest.main()
