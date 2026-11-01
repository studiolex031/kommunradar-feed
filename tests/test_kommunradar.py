import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest, feed


class FeedTest(unittest.TestCase):
    def test_normalize_maps_region_category_value_and_strips_prefix(self):
        n = feed.normalize({"publication-number": "1-2026", "notice-title": {"swe": ["Sverige – Städtjänster – Lokalvård skolor"]},
                            "buyer-name": {"swe": ["Malmö stad"]}, "publication-date": "2026-10-30+01:00",
                            "deadline-receipt-tender-date-lot": ["2026-12-01Z", "2026-11-20Z"], "notice-type": "cn-standard",
                            "classification-cpv": ["90910000", "90910000"], "place-of-performance": ["SE224", "SWE"],
                            "estimated-value-lot": ["2500000", "99999999999999"]})
        self.assertEqual(n["title"], "Lokalvård skolor")
        self.assertEqual(n["region"], "Skåne")
        self.assertEqual(n["categories"], ["Avfall, städ & miljö"])
        self.assertEqual(n["deadline"], "2026-11-20")
        self.assertEqual(n["value_sek"], 2500000)  # placeholder value ignored

    def test_only_open_calls_for_tender(self):
        self.assertTrue(feed.is_open({"type": "cn-standard", "deadline": "2026-12-01"}, "2026-11-01"))
        self.assertFalse(feed.is_open({"type": "can-standard", "deadline": ""}, "2026-11-01"))
        self.assertFalse(feed.is_open({"type": "cn-standard", "deadline": "2026-10-01"}, "2026-11-01"))


class DigestTest(unittest.TestCase):
    lead = {"id": "1", "title": "Lokalvård skolor", "buyer": "Malmö stad", "city": "MALMÖ", "region": "Skåne",
            "categories": ["Avfall, städ & miljö"], "url": "https://ted", "deadline": "2026-11-20", "value_sek": 2500000}

    def test_matching_by_keyword_and_region(self):
        self.assertTrue(digest.matches(self.lead, digest.keywords("lokalvård, fönster"), "skane"))
        self.assertTrue(digest.matches(self.lead, digest.keywords("städ"), "alla"))
        self.assertFalse(digest.matches(self.lead, digest.keywords("städ"), "stockholm"))
        self.assertFalse(digest.matches(self.lead, digest.keywords("catering"), "skane"))
        self.assertTrue(digest.matches({**self.lead, "region": ""}, [], "stockholm"))  # unknown region kept

    def test_new_leads_against_previous_snapshot(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"leads": [{"id": "1"}]}, f)
        self.assertEqual([l["id"] for l in digest.new_leads([{"id": "1"}, {"id": "2"}], f.name)], ["2"])

    def test_email_escapes_content(self):
        out = digest.render([{**self.lead, "title": "<script>x</script>"}], {"keywords": "städ", "lan": "skane"}, "https://k", "")
        self.assertNotIn("<script>", out); self.assertIn("1 nya upphandlingar", out)


    def test_reads_answers_from_script_and_dashboard_payment_links(self):
        script = [{"key": "bevakning", "text": {"value": "städ, fönster"}}, {"key": "lan", "dropdown": {"value": "skane"}}]
        self.assertEqual(digest.read_answers(script), {"bevakning": "städ, fönster", "lan": "skane"})
        manual = [{"key": "bevakningsord", "label": {"custom": "Bevakningsord"}, "text": {"value": "IT-konsult"}},
                  {"key": "ln", "label": {"custom": "Län"}, "text": {"value": "Västra Götaland"}}]
        self.assertEqual(digest.read_answers(manual), {"bevakning": "IT-konsult", "lan": "vastragotaland"})
        self.assertEqual(digest.read_answers([{"key": "x", "label": {"custom": "Län"}, "text": {"value": "hela sverige"}}]), {"lan": "alla"})


if __name__ == "__main__":
    unittest.main()
