"""Startar morgonens GitHub Actions-körningar i tid (Vercel Cron → workflow_dispatch).

GitHubs egna schema har startat körningarna 7–11 timmar sent varje dag sedan
början av november. Vercel Cron anropar den här funktionen kl. 06–07 svensk
tid; den startar workflowerna direkt via GitHubs API. GitHubs schema ligger
kvar som reserv, men hoppar över sig själv om en körning redan startats i dag
(se jobbet "gate" i varje workflow).

Miljövariabler (bara på servern, i Vercel-projektet):
  GH_DISPATCH_TOKEN  fine-grained token: bara repot kommunradar-feed, Actions: Read and write
  CRON_SECRET        Vercel skickar den som "Authorization: Bearer ..." vid cron-anrop
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

REPO = "studiolex031/kommunradar-feed"
VARJE_DAG = ["daily.yml"]
VARDAGAR = ["winner-leads.yml", "outbound-vinnare.yml", "followup-vinnare.yml",
            "social-daily.yml", "x-daily.yml"]
MANDAGAR = ["weekly.yml", "linkedin-network.yml"]


def workflows_for(dag):
    """Workflow-filer att starta en given dag (datetime.date, svensk tid)."""
    wf = list(VARJE_DAG)
    if dag.weekday() < 5:
        wf += VARDAGAR
    if dag.weekday() == 0:
        wf += MANDAGAR
    return wf


def dispatch(wf, token):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/dispatches",
        data=json.dumps({"ref": "main"}).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "kommunradar-dispatch"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class handler(BaseHTTPRequestHandler):
    def _svar(self, kod, data):
        body = json.dumps(data).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        secret, token = os.environ.get("CRON_SECRET"), os.environ.get("GH_DISPATCH_TOKEN")
        if not secret or self.headers.get("Authorization") != f"Bearer {secret}":
            return self._svar(401, {"error": "unauthorized"})
        if not token:
            return self._svar(500, {"error": "GH_DISPATCH_TOKEN saknas"})
        idag = datetime.now(ZoneInfo("Europe/Stockholm")).date()
        res = {wf: dispatch(wf, token) for wf in workflows_for(idag)}
        ok = all(k == 204 for k in res.values())
        return self._svar(200 if ok else 502, {"datum": idag.isoformat(), "resultat": res})
