"""Bevakar omnämnanden av Kommunradars X-konto och mejlar nya till REPORT_TO (hej@), så att de besvaras i tid.

    python scripts/x_mentions.py      # läser x-state.json (since_id), mejlar nya omnämnanden, skriver ny since_id

Svarar aldrig själv: varje svar på X skickas av en människa efter godkännande. Kräver X_*-nycklarna.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from x_daily import mail, x_keys, x_request  # noqa: E402

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "x-state.json")


def format_mentions(resp):
    users = {u["id"]: u["username"] for u in resp.get("includes", {}).get("users", [])}
    lines = []
    for t in resp.get("data", []):
        who = users.get(t.get("author_id"), "okänd")
        lines.append(f"@{who} ({t.get('created_at', '')[:16].replace('T', ' ')}):\n{t['text']}\n"
                     f"https://x.com/{who}/status/{t['id']}\n")
    return lines


def main():
    keys = x_keys()
    if not keys:
        print("X-nycklar saknas, hoppar över"); return
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    uid = state.get("user_id") or x_request("GET", "https://api.x.com/2/users/me", keys)["data"]["id"]
    lines, newest = fetch_all(uid, keys, state.get("since_id"))
    newest = newest or state.get("since_id")
    if lines and state.get("started"):  # allra första körningen sätter bara startpunkten
        mail(f"X-omnämnande: {len(lines)} nya att svara på",
             "Nya omnämnanden av Kommunradar på X. Svara från appen; inget besvaras automatiskt.\n\n" + "\n".join(lines), [])
    json.dump({"user_id": uid, "since_id": newest, "started": True}, open(STATE, "w"))
    print(f"{len(lines)} nya omnämnanden")


def fetch_all(uid, keys, since_id, max_pages=10, request=None):
    """Alla sidor sedan since_id; newest_id från första sidan (den nyaste). Högst max_pages sidor per körning."""
    request = request or x_request
    params = {"max_results": "50", "tweet.fields": "author_id,created_at", "expansions": "author_id",
              "user.fields": "username"}
    if since_id:
        params["since_id"] = since_id
    lines, newest = [], None
    for _ in range(max_pages):
        resp = request("GET", f"https://api.x.com/2/users/{uid}/mentions", keys, params=params)
        lines += format_mentions(resp)
        meta = resp.get("meta", {})
        newest = newest or meta.get("newest_id")
        if not meta.get("next_token"):
            break
        params = {**params, "pagination_token": meta["next_token"]}
    return lines, newest


if __name__ == "__main__":
    main()
