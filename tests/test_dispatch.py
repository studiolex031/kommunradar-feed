import importlib.util, os, unittest
from datetime import date

p = os.path.join(os.path.dirname(__file__), "..", "dispatch", "api", "dispatch.py")
spec = importlib.util.spec_from_file_location("dispatch", p)
D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
WF = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows")


UTAN_GATE = {"outbound-vinnare.yml"}


class Dispatch(unittest.TestCase):
    def test_mandag(self):
        wf = D.workflows_for(date(2026, 11, 30))
        self.assertIn("weekly.yml", wf); self.assertIn("outbound-vinnare.yml", wf)

    def test_onsdag(self):
        wf = D.workflows_for(date(2026, 11, 25))
        self.assertIn("outbound-vinnare.yml", wf); self.assertNotIn("weekly.yml", wf)

    def test_lordag_bara_daily(self):
        self.assertEqual(D.workflows_for(date(2026, 11, 28)), ["daily.yml"])

    # outbound-vinnare räknar dagens tak ur state, så en sen reservkörning skickar inget extra.
    # En gate där skulle i stället stoppa live-körningen om en kontroll/torrkörning gjorts samma dag.
    def test_alla_filer_finns_och_har_dispatch_och_gate(self):
        alla = D.VARJE_DAG + D.VARDAGAR + D.MANDAGAR
        for f in alla:
            s = open(os.path.join(WF, f), encoding="utf8").read()
            self.assertIn("workflow_dispatch", s, f)
            if f in UTAN_GATE:
                continue
            self.assertIn("gate:", s, f)
            self.assertIn("needs: gate", s, f)


if __name__ == "__main__":
    unittest.main()
