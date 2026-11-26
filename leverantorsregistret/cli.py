import argparse, json, os
from . import data, deliver, state, stripe_sync, xlsx

PLANER = {"p1": ("p1", data.P1_KOLUMNER, "Nya vinnare varje vecka"),
          "p2": ("p2", data.P2_KOLUMNER, "Avtal som löper ut")}


def parser():
    cli = argparse.ArgumentParser(description="Leverans av Leverantörsregistret-prenumerationer")
    cli.add_argument("--mode", choices=("all", "p1", "p2", "first"), default="all")
    cli.add_argument("--dry-run", action="store_true")
    cli.add_argument("--test-to", default=deliver.TEST_TO)
    cli.add_argument("--state", default=".github/leverantorsregistret/leveranser.json")
    cli.add_argument("--rapport", default=".github/leverantorsregistret/rapport.json")
    return cli


def fake_subscribers(mode):
    folk = []
    if mode in ("all", "p1", "first"):
        folk.append({"id": "dry_p1", "email": deliver.TEST_TO, "plan": "p1",
                     "bransch": None, "lan": None, "customer_id": "dry_cus_p1"})
    if mode in ("all", "p2", "first"):
        folk.append({"id": "dry_p2", "email": deliver.TEST_TO, "plan": "p2",
                     "bransch": None, "lan": None, "customer_id": "dry_cus_p2"})
    return folk


def hanta_rader(plan, subscriber, now=None):
    if plan == "p1":
        query = data.p1_query()
        notices = data.fetch_notices(query)
        coverage = data.coverage(notices)
        rader = data.p1_rows(notices, subscriber.get("bransch"), subscriber.get("lan"))
    else:
        query = data.p2_query()
        notices = data.fetch_notices(query, max_pages=60)
        coverage = data.coverage(notices)
        rader = data.p2_rows(notices, subscriber.get("bransch"), subscriber.get("lan"))
    return rader, coverage


def skriv_rapport(path, rapport):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rapport, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    args = parser().parse_args(argv)
    if args.dry_run and args.test_to != deliver.TEST_TO:
        raise RuntimeError("Torrkörning får bara skickas till hej@kommunradar.online")
    log = state.DeliveryLog.load(args.state)
    prenumeranter = fake_subscribers(args.mode) if args.dry_run else list(stripe_sync.subscribers())
    rapport = {"dry_run": args.dry_run, "läge": args.mode, "leveranser": [], "täckning": {}}
    for subscriber in prenumeranter:
        plan = subscriber.get("plan")
        if plan not in PLANER or (args.mode in PLANER and args.mode != plan):
            continue
        if args.mode == "first" and log.har_leverans(subscriber.get("id", ""), plan, "first"):
            continue
        if not args.dry_run and not log.is_due(subscriber):
            continue
        rader, coverage = hanta_rader(plan, subscriber)
        rapport["täckning"][plan] = coverage
        if plan == "p2" and coverage["tackning_slutdatum"] < 0.5 and not args.dry_run:
            raise RuntimeError(f"P2-täckning för låg: {coverage['tackning_slutdatum']}")
        _, kolumner, _ = PLANER[plan]
        innehall = xlsx.write_xlsx(rader, kolumner, "Leverantörsregistret")
        skickat = deliver.send_email(subscriber, plan, rader, innehall,
                                     dry_run=args.dry_run, test_to=args.test_to)
        period = "first" if not log.har_leverans(subscriber.get("id", ""), plan, "first") else state.period_for(plan)
        if not args.dry_run:
            log.mark(subscriber, plan, period,
                     {"rader": len(rader), "filnamn": deliver.filnamn(plan),
                      "meddelande_id": skickat.get("id", ""), "period": period})
            log.save(args.state)
        rapport["leveranser"].append({"plan": plan, "period": period, "rader": len(rader),
                                      "mottagare": state.hash_email(subscriber.get("email")),
                                      "meddelande_id": skickat.get("id", "")})
    if not args.dry_run:
        skriv_rapport(args.rapport, rapport)
    print(json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True))
    return rapport
