import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import demo_patch as dp

LIVE = ("<!--pp:s--><form id=\"kr-demo-form\"></form><script>fetch('/api/demo-signup.php').then(function (d) {\n"
        "        " + dp.OLD + "\n        msg.textContent = d.error || 'Något gick fel.';})</script>")


class DemoPatch(unittest.TestCase):
    def test_redirecten_byts_mot_traffar_pa_sidan(self):
        out = dp.patch(LIVE)
        self.assertNotIn("window.location.href = d.redirect", out)
        self.assertIn("search()", out)
        self.assertIn("scrollIntoView", out)
        self.assertNotIn("login.kommunradar.online", out)

    def test_idempotent(self):
        once = dp.patch(LIVE)
        self.assertEqual(dp.patch(once), once)

    def test_okand_sida_stoppar(self):
        with self.assertRaises(SystemExit):
            dp.patch("<html>annan sida</html>")


if __name__ == "__main__":
    unittest.main()
