import calendar, hashlib, json
from datetime import date, datetime, time, timedelta, timezone

UTC = timezone.utc


def last_sunday(year, month):
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() + 1) % 7)


def stockholm_now(value=None):
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    summer_start = datetime.combine(last_sunday(moment.year, 3), time(2), tzinfo=UTC)
    summer_end = datetime.combine(last_sunday(moment.year, 10), time(3), tzinfo=UTC)
    offset = 2 if summer_start <= moment < summer_end else 1
    return moment.astimezone(timezone(timedelta(hours=offset)))


def period_for(plan, value=None):
    local = stockholm_now(value)
    if plan == "p1":
        year, week, _ = local.date().isocalendar()
        return f"week:{year}-W{week:02d}"
    return f"month:{local.year:04d}-{local.month:02d}"


def first_weekday(year, month):
    day = date(year, month, 1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day


def hash_email(email):
    return hashlib.sha256(str(email or "").strip().casefold().encode()).hexdigest()[:16]


def tidpunkt(text):
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


class DeliveryLog:
    def __init__(self, data=None):
        self.data = data or {"version": 1, "leveranser": {}}
        self.data.setdefault("leveranser", {})

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as handle:
                return cls(json.load(handle))
        except FileNotFoundError:
            return cls()

    def save(self, path):
        import os
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    def nyckel(self, subscription_id, plan, period):
        return f"{subscription_id}|{plan}|{period}"

    def har_leverans(self, subscription_id, plan, period):
        return self.nyckel(subscription_id, plan, period) in self.data["leveranser"]

    def is_due(self, subscriber, now=None):
        local = stockholm_now(now)
        subscription_id, plan = subscriber.get("id", ""), subscriber.get("plan", "")
        prefix = f"{subscription_id}|{plan}|"
        egna = {key: value for key, value in self.data["leveranser"].items() if key.startswith(prefix)}
        if not egna:
            return True
        current = period_for(plan, local)
        if self.har_leverans(subscription_id, plan, current):
            return False
        first = egna.get(self.nyckel(subscription_id, plan, "first"))
        if first:
            sent = tidpunkt(first.get("tid"))
            if sent and period_for(plan, sent) == current:
                return False
        if local.hour != 7:
            return False
        if plan == "p1":
            return local.weekday() == 0
        if plan == "p2":
            return local.date() == first_weekday(local.year, local.month)
        return False

    def mark(self, subscriber, plan, period, information, now=None):
        local = stockholm_now(now)
        info = {"tid": local.isoformat(), "plan": plan,
                "prenumeration": subscriber.get("id", ""),
                "mottagare": hash_email(subscriber.get("email")), "period": period}
        info.update(information or {})
        self.data["leveranser"][self.nyckel(subscriber.get("id", ""), plan, period)] = info
        self.data["senast"] = info["tid"]
