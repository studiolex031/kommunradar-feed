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

    def test_non_sek_lot_makes_value_unknown_and_all_regions_kept(self):
        base = {"publication-number": "2-2026", "notice-type": "cn-standard", "place-of-performance": ["SE110", "SE224"],
                "estimated-value-lot": ["100", "200"]}
        self.assertIsNone(feed.normalize({**base, "estimated-value-cur-lot": ["SEK", "EUR"]})["value_sek"])
        n = feed.normalize({**base, "estimated-value-cur-lot": ["SEK", "SEK"]})
        self.assertEqual((n["value_sek"], n["regions"]), (300, ["Stockholm", "Skåne"]))

    def test_multi_lot_notice_open_while_any_lot_open(self):
        n = feed.normalize({"publication-number": "3", "notice-type": "cn-standard",
                            "deadline-receipt-tender-date-lot": ["2026-10-01Z", "2026-12-01Z"]})
        self.assertTrue(feed.is_open(n, "2026-11-01"))

    def test_only_open_calls_for_tender(self):
        self.assertTrue(feed.is_open({"type": "cn-standard", "deadline": "2026-12-01"}, "2026-11-01"))
        self.assertFalse(feed.is_open({"type": "can-standard", "deadline": ""}, "2026-11-01"))
        self.assertFalse(feed.is_open({"type": "cn-standard", "deadline": "2026-10-01"}, "2026-11-01"))


class FetchRetryTest(unittest.TestCase):
    def test_retries_on_rate_limit(self):
        import io, urllib.error
        from unittest import mock
        calls = []
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        def fake(req, timeout):
            calls.append(1)
            if len(calls) < 3: raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return Resp(b'{"notices": []}')
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"), mock.patch("sys.stderr"):
            self.assertEqual(feed.fetch(), {"notices": []})
        self.assertEqual(len(calls), 3)


class RetryAfterTest(unittest.TestCase):
    def test_seconds_date_and_garbage(self):
        import email.utils, datetime as dt
        self.assertEqual(feed.retry_after("7"), 7)
        self.assertIsNone(feed.retry_after("soon"))
        later = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60))
        self.assertTrue(50 <= feed.retry_after(later) <= 60)


class DigestTest(unittest.TestCase):
    lead = {"id": "1", "title": "Lokalvård skolor", "buyer": "Malmö stad", "city": "MALMÖ", "region": "Skåne",
            "categories": ["Avfall, städ & miljö"], "url": "https://ted", "deadline": "2026-11-20", "value_sek": 2500000}

    def test_matching_by_keyword_and_region(self):
        self.assertTrue(digest.matches(self.lead, digest.keywords("lokalvård, fönster"), "skane"))
        self.assertTrue(digest.matches(self.lead, digest.keywords("städ"), "alla"))
        self.assertFalse(digest.matches(self.lead, digest.keywords("städ"), "stockholm"))
        self.assertFalse(digest.matches(self.lead, digest.keywords("catering"), "skane"))
        self.assertTrue(digest.matches({**self.lead, "region": ""}, [], "stockholm"))  # unknown region kept
        self.assertTrue(digest.matches({**self.lead, "regions": ["Stockholm", "Skåne"]}, [], "skane"))

    def test_new_leads_against_previous_snapshot(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"leads": [{"id": "1"}]}, f)
        self.assertEqual([l["id"] for l in digest.new_leads([{"id": "1"}, {"id": "2"}], f.name)], ["2"])

    def test_missing_key_fails_unless_dry_run(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": ""}), mock.patch.object(sys, "argv", ["digest.py", "--prev", "x"]), \
                mock.patch("digest.new_leads", return_value=[]), mock.patch("builtins.open", mock.mock_open(read_data='{"leads": []}')):
            with self.assertRaises(SystemExit) as e: digest.main()
            self.assertTrue(str(e.exception.code).startswith("STRIPE_SECRET_KEY saknas"))
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": ""}), mock.patch.object(sys, "argv", ["digest.py", "--dry-run"]), \
                mock.patch("digest.new_leads", return_value=[]), mock.patch("builtins.open", mock.mock_open(read_data='{"leads": []}')), \
                mock.patch("sys.stdout"):
            digest.main()  # dry-run without key is fine

    def test_more_than_max_matches_are_split_across_mails(self):
        from unittest import mock
        leads = [{**self.lead, "id": str(i)} for i in range(digest.MAX_PER_MAIL + 5)]
        smtp = mock.MagicMock()
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_x"}), mock.patch.object(sys, "argv", ["digest.py"]), \
                mock.patch("digest.new_leads", return_value=leads), mock.patch("builtins.open", mock.mock_open(read_data='{"leads": []}')), \
                mock.patch("digest.smtp_connect", return_value=smtp), mock.patch("sys.stdout"), \
                mock.patch("digest.subscribers", return_value=iter([{"email": "a@b.se", "keywords": "", "lan": "alla"}])):
            digest.main()
        self.assertEqual(smtp.send_message.call_count, 2)

    def test_email_escapes_content(self):
        out = digest.render([{**self.lead, "title": "<script>x</script>"}], {"keywords": "städ", "lan": "skane"}, "https://k", "")
        self.assertNotIn("<script>", out); self.assertIn("1 nya upphandlingar", out)


    def test_reads_answers_from_script_and_dashboard_payment_links(self):
        script = [{"key": "bevakning", "text": {"value": "städ, fönster"}}, {"key": "lan", "dropdown": {"value": "skane"}}]
        self.assertEqual(digest.read_answers(script), {"bevakning": "städ, fönster", "lan": "skane"})
        manual = [{"key": "bevakningsord", "label": {"custom": "Bevakningsord"}, "text": {"value": "IT-konsult"}},
                  {"key": "ln", "label": {"custom": "Län"}, "text": {"value": "Västra Götaland"}}]
        self.assertEqual(digest.read_answers(manual), {"bevakning": "IT-konsult", "lan": "vastragotaland"})
        city_keyword = [{"key": "bevakning", "text": {"value": "Stockholm"}}, {"key": "lan", "dropdown": {"value": "skane"}}]
        self.assertEqual(digest.read_answers(city_keyword), {"bevakning": "Stockholm", "lan": "skane"})
        self.assertEqual(digest.read_answers([{"key": "x", "label": {"custom": "Län"}, "text": {"value": "hela sverige"}}]), {"lan": "alla"})


class OnboardingTest(unittest.TestCase):
    import datetime as _dt
    start = int(_dt.datetime(2026, 11, 6, 14, 0, tzinfo=_dt.timezone.utc).timestamp())

    def sub(self, **kw):
        return {"email": "a@b.se", "keywords": "", "lan": "alla", "status": "trialing", "trial_start": self.start, **kw}

    def test_right_mail_on_day_1_3_6_and_none_otherwise(self):
        import datetime as dt
        day = lambda n: digest.onboarding_mail(self.sub(), dt.date(2026, 11, 6) + dt.timedelta(days=n))
        self.assertIn("Välkommen", day(1)[0])
        self.assertIn("rätt upphandlingar", day(3)[0])
        self.assertIn("slutar i morgon", day(6)[0])
        for n in (0, 2, 4, 5, 7, 8): self.assertIsNone(day(n))

    def test_paying_or_cancelled_customers_get_no_trial_mail(self):
        import datetime as dt
        for status in ("active", "canceled", "past_due"):
            self.assertIsNone(digest.onboarding_mail(self.sub(status=status), dt.date(2026, 11, 12)))
        self.assertIsNone(digest.onboarding_mail(self.sub(trial_start=None), dt.date(2026, 11, 7)))

    def test_portal_link_only_when_set(self):
        import datetime as dt
        self.assertIn("här: https://portal", digest.onboarding_mail(self.sub(), dt.date(2026, 11, 12), "https://portal")[1])
        self.assertNotIn("{portal}", digest.onboarding_mail(self.sub(), dt.date(2026, 11, 12))[1])

    def test_trial_mail_sent_even_without_new_leads(self):
        from unittest import mock
        import datetime as dt
        smtp = mock.MagicMock()
        fixed = dt.datetime(2026, 11, 7, 6, 0, tzinfo=dt.timezone.utc)
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_x"}), mock.patch.object(sys, "argv", ["digest.py"]), \
                mock.patch("digest.new_leads", return_value=[]), mock.patch("builtins.open", mock.mock_open(read_data='{"leads": []}')), \
                mock.patch("digest.smtp_connect", return_value=smtp), mock.patch("sys.stdout"), \
                mock.patch("digest.subscribers", return_value=iter([self.sub()])), \
                mock.patch("digest.dt.datetime", wraps=dt.datetime) as clock:
            clock.now.return_value = fixed
            digest.main()
        self.assertEqual(smtp.send_message.call_count, 1)
        msg = smtp.send_message.call_args[0][0]
        self.assertIn("Välkommen", msg["Subject"]); self.assertEqual(msg["Reply-To"], "hej@kommunradar.online")


class VeckobrevTest(unittest.TestCase):
    import datetime as _dt
    today = _dt.date(2026, 11, 16)  # en måndag
    lead = {"id": "1", "title": "Lokalvård skolor", "buyer": "Malmö stad", "city": "MALMÖ", "region": "Skåne",
            "categories": ["Avfall, städ & miljö"], "url": "https://ted", "deadline": "2026-12-20", "published": "2026-11-12",
            "value_sek": 2500000}

    def ts(self, y, m, d):
        import datetime as dt
        return int(dt.datetime(y, m, d, 14, tzinfo=dt.timezone.utc).timestamp())

    def free(self, **kw):
        return {"email": "f@b.se", "keywords": "städ", "lan": "skane", "status": "active", "trial_start": None,
                "tier": "veckobrev", "created": self.ts(2026, 11, 1), **kw}

    def test_product_tier_from_metadata_or_name(self):
        self.assertEqual(digest.product_tier({"metadata": {"tier": "veckobrev"}, "name": "X"}), "veckobrev")
        self.assertEqual(digest.product_tier({"metadata": {}, "name": "Kommunradar Veckobrev"}), "veckobrev")
        self.assertEqual(digest.product_tier({"metadata": {"app": "kommunradar"}, "name": "Kommunradar Pro"}), "pro")
        self.assertEqual(digest.product_tier({"metadata": {"tier": "pro"}, "name": "Kommunradar veckobrev"}), "pro")

    def test_weekly_hits_last_7_days_biggest_first(self):
        old = {**self.lead, "id": "old", "published": "2026-11-01"}
        small = {**self.lead, "id": "small", "value_sek": 100000}
        other_lan = {**self.lead, "id": "sthlm", "region": "Stockholm"}
        hits, fallback = digest.weekly_hits([small, old, self.lead, other_lan], self.free(), self.today)
        self.assertEqual([l["id"] for l in hits], ["1", "small"]); self.assertFalse(fallback)

    def test_weekly_falls_back_to_county_when_no_keyword_hit(self):
        hits, fallback = digest.weekly_hits([self.lead], self.free(keywords="catering"), self.today)
        self.assertEqual(len(hits), 1); self.assertTrue(fallback)
        self.assertEqual(digest.weekly_hits([], self.free(keywords="catering"), self.today), ([], True))
        unknown = {**self.lead, "id": "u", "region": "", "regions": []}
        self.assertEqual(digest.weekly_hits([unknown], self.free(keywords="catering"), self.today), ([], True))

    def test_pro_customers_and_pro_mails_never_mix_with_free(self):
        pro = {"email": "F@b.se", "keywords": "", "lan": "alla", "status": "active", "tier": "pro"}
        self.assertEqual(digest.weekly_recipients([self.free(), pro]), [])
        self.assertEqual(digest.weekly_recipients([self.free()]), [self.free()])
        self.assertIsNone(digest.onboarding_mail(self.free(status="trialing", trial_start=self.ts(2026, 11, 15)), self.today))

    def test_weekly_mail_escapes_shows_max_and_upsell(self):
        many = [{**self.lead, "id": str(i), "title": "<b>x</b>"} for i in range(digest.WEEKLY_MAX + 3)]
        out = digest.render_weekly(many, self.free(), False, False, "https://k", "https://k/#pris", "https://portal")
        self.assertNotIn("<b>x</b>", out); self.assertIn("13 nya upphandlingar", out)
        self.assertIn("3 till", out); self.assertIn("https://k/#pris", out); self.assertIn("avsluta", out)
        self.assertEqual(out.count("https://ted"), digest.WEEKLY_MAX)
        msg = digest.weekly_message(self.free(), many, False, False, "https://k", "https://k/#pris", "https://portal", "hej@k.se")
        self.assertIn("mailto:hej@k.se?subject=avsluta", msg["List-Unsubscribe"])

    def run_main(self, argv, subs, now):
        from unittest import mock
        import datetime as dt
        smtp = mock.MagicMock()
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_x"}), mock.patch.object(sys, "argv", argv), \
                mock.patch("digest.new_leads", return_value=[]), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps({"leads": [self.lead]}))), \
                mock.patch("digest.smtp_connect", return_value=smtp), mock.patch("sys.stdout"), \
                mock.patch("digest.subscribers", return_value=iter(subs)), \
                mock.patch("digest.dt.datetime", wraps=dt.datetime) as clock:
            clock.now.return_value = dt.datetime.combine(now, dt.time(6), dt.timezone.utc)
            digest.main()
        return [c[0][0] for c in smtp.send_message.call_args_list]

    def test_daily_run_welcomes_free_signup_the_morning_after_only(self):
        import datetime as dt
        yesterday = self.free(created=self.ts(2026, 11, 15))
        sent = self.run_main(["digest.py"], [yesterday, self.free(email="old@b.se")], self.today)
        self.assertEqual([m["To"] for m in sent], ["f@b.se"]); self.assertIn("Välkommen", sent[0]["Subject"])
        self.assertEqual(self.run_main(["digest.py"], [yesterday], self.today + dt.timedelta(days=1)), [])

    def test_weekly_run_skips_signups_from_yesterday_and_today(self):
        subs = [self.free(), self.free(email="y@b.se", created=self.ts(2026, 11, 15)),
                self.free(email="t@b.se", created=self.ts(2026, 11, 16))]
        sent = self.run_main(["digest.py", "--weekly"], subs, self.today)
        self.assertEqual([m["To"] for m in sent], ["f@b.se"]); self.assertIn("i veckan", sent[0]["Subject"])


if __name__ == "__main__":
    unittest.main()
