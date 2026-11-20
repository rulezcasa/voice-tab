"""Fill a freshly reset database with demo people, groups, venues, calendars and about 30 expenses.

    python -m scripts.reset_db && python -m scripts.seed
    python -m scripts.reset_db --db tab_drill && python -m scripts.seed --db tab_drill

All dates are relative to today (config.TZ), so the demo lines keep working any day:
  - "What did I spend 20 dollars on last Wednesday?"  -> a $20 cab on the most recent Wednesday
  - "How much on rides this month?"                   -> Uber/Lyft rides spread over the last 3 weeks
  - "Dinner with Sam and Alex"                        -> two people share the alias "Alex"
  - Meetup planning for "Friday crew" (Nik, Sam, Priya, Alex Chen):
      * the coming Saturday 2pm-6pm is the only time all four are free
      * Friday evening misses Alex Chen, Sunday late morning misses Priya
      * The Gilded Steakhouse is over everyone's budget, Locked In Escape Room is outside Priya's
        4-mile radius, Hayes Karaoke is just over Priya's budget, Pacifica Taproom is outside the
        search circle, the Dolores Park picnic is outdoor (dropped when rain is likely)
      * a past bowling meetup cost $136 for 4, so the planner "learns" bowling is $34/pp, not the listed
        $22, which pushes Lucky Lanes over Priya's budget (a good "it learns from real spending" moment)
      * what's left: board game cafe, coffee, pub, arcade bar, ramen, dumplings (top 3 shown)
Expenses are written through the ledger (exact shares + embeddings) and flagged is_demo.
"""
import argparse
import json

from scripts._db import pick_db

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--me", default="Nik", help="the account owner's name (default: Nik)")
args = pick_db(parser)

from datetime import date, datetime, time, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from src import config  # noqa: E402
from src.core import dates  # noqa: E402
from src.core.expenses import ledger  # noqa: E402
from src.db.s2_client import cursor, to_vector  # noqa: E402
from src.model.embeddings import embed  # noqa: E402

DAY_START, DAY_END = time(9), time(23)

# name, is_me, aliases, (lat, lng), budget, radius_mi, max_travel_min, mode, interests
PEOPLE = [
    (args.me, True, [], (37.7599, -122.4148), "40", 6.0, 40, "transit", ["ramen", "bowling", "cafe"]),         # Mission
    ("Sam", False, ["Sammy"], (37.7785, -122.4056), "50", 12.0, 35, "drive", ["bowling", "bar"]),             # SoMa
    ("Priya", False, ["Pri"], (37.7502, -122.4337), "30", 4.0, 40, "transit", ["cafe", "escape_room"]),       # Noe Valley
    ("Alex Chen", False, ["Alex", "Chen"], (37.7759, -122.4245), "35", 5.0, 30, "bike", ["ramen", "bar"]),    # Hayes Valley
    ("Alex Park", False, ["Alex", "Park"], (37.7530, -122.4940), "45", 8.0, 40, "drive", ["karaoke"]),        # Sunset
]

GROUPS = [
    ("Apt 4B", ["roommates", "roomies", "flatmates", "the apartment"], [args.me, "Sam", "Priya"]),
    ("Friday crew", ["the crew", "crew", "friends", "the gang", "the four of us"], [args.me, "Sam", "Priya", "Alex Chen"]),
]

# name, kind, (lat, lng), price_pp, parking, indoor, description
VENUES = [
    ("Lucky Lanes Bowling", "bowling", (37.7637, -122.4180), "22", "10", True, "bowling alley with shoe rental and snacks"),
    ("Steep Coffee Co.", "cafe", (37.7564, -122.4214), "9", "0", True, "quiet cafe, pastries, good for catching up"),
    ("Valencia Board Game Cafe", "cafe", (37.7610, -122.4215), "12", "0", True, "board games, coffee and snacks"),
    ("Tonkotsu Corner", "ramen", (37.7640, -122.4230), "20", "0", True, "ramen and izakaya small plates"),
    ("Corner Pub", "bar", (37.7650, -122.4220), "18", "0", True, "neighborhood bar with pool tables"),
    ("Hayes Karaoke", "karaoke", (37.7766, -122.4230), "25", "8", True, "private karaoke rooms"),
    ("Dolores Park picnic", "park", (37.7596, -122.4269), "6", "0", False, "outdoor picnic on the lawn, bring snacks"),
    ("Locked In Escape Room", "escape_room", (37.7820, -122.5000), "28", "5", True, "60-minute escape room for 4 to 6"),
    ("The Gilded Steakhouse", "steakhouse", (37.7946, -122.3999), "85", "20", True, "upscale steakhouse"),
    ("Pacifica Taproom", "bar", (37.6138, -122.4869), "16", "0", True, "beer hall by the beach"),
    ("Mission Arcade Bar", "bar", (37.7590, -122.4190), "15", "0", True, "retro arcade games and drinks"),
    ("Hayes Dumpling House", "dining", (37.7760, -122.4260), "17", "0", True, "dumplings and noodles, shareable plates"),
]

# Free windows (hour ranges) per person relative to the coming weekend. Everything else 9am-11pm is busy.
FREE = {
    "sat": {args.me: (14, 18), "Sam": (13, 19), "Priya": (14, 18), "Alex Chen": (12, 18), "Alex Park": (10, 12)},
    "fri": {args.me: (19, 23), "Sam": (18, 23), "Priya": (19, 22), "Alex Park": (19, 23)},   # Alex Chen busy
    "sun": {args.me: (11, 14), "Sam": (10, 14), "Alex Chen": (11, 13), "Alex Park": (15, 18)},  # Priya busy
}
BUSY_LABELS = ["Work", "Dentist", "Climbing gym", "Family call", "Class", "Errands", "Work dinner", "Shift"]


def try_embed(texts: list[str]) -> list[str | None]:
    try:
        return [to_vector(v) for v in embed(texts)]
    except Exception as e:
        print(f"  (embeddings skipped: {type(e).__name__}: {e})")
        return [None] * len(texts)


def weekend(today: date) -> dict[str, date]:
    sat = today + timedelta(days=(5 - today.weekday()) % 7 or 7)   # the coming Saturday, never today
    fri = sat - timedelta(days=1)
    if fri <= today:
        fri = sat + timedelta(days=6)
    return {"fri": fri, "sat": sat, "sun": sat + timedelta(days=1)}


def busy_blocks(free_by_day: dict[date, tuple[int, int]], first: date, last: date, offset: int) -> list[tuple]:
    """Busy = 9am-11pm minus the free window, for each day first..last. Labels are private."""
    out, n = [], offset
    d = first
    while d <= last:
        lo, hi = datetime.combine(d, DAY_START), datetime.combine(d, DAY_END)
        f = free_by_day.get(d)
        spans = [(lo, hi)] if not f else [(lo, datetime.combine(d, time(f[0]))), (datetime.combine(d, time(f[1])) if f[1] < 24 else hi, hi)]
        for s, e in spans:
            if e > s:
                out.append((s, e, BUSY_LABELS[n % len(BUSY_LABELS)]))
                n += 1
        d += timedelta(days=1)
    return out


def main() -> None:
    today = ledger.today()
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM people")
        if cur.fetchone()[0]:
            raise SystemExit("people already has rows: run python -m scripts.reset_db first")

    print(f"Seeding '{config.SS['database']}' for today = {today} ({config.TZ})")

    # ---------- people ----------
    vecs = try_embed([" ".join([p[0], *p[2]]) for p in PEOPLE])
    ids: dict[str, int] = {}
    with cursor() as cur:
        for (name, is_me, aliases, (lat, lng), budget, radius, max_min, mode, interests), vec in zip(PEOPLE, vecs):
            cur.execute(
                "INSERT INTO people (name, is_me, aliases, embedding, home_lat, home_lng, meetup_budget,"
                " max_radius_mi, max_travel_min, travel_mode, interests) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, is_me, json.dumps(aliases), vec, lat, lng, budget, radius, max_min, mode, json.dumps(interests)))
            ids[name] = cur.lastrowid
    ledger.me_id.cache_clear()
    me = ids[args.me]
    print(f"  people: {', '.join(ids)}")

    # ---------- groups ----------
    vecs = try_embed([" ".join([g[0], *g[1]]) for g in GROUPS])
    gids: dict[str, int] = {}
    with cursor() as cur:
        for (name, aliases, members), vec in zip(GROUPS, vecs):
            cur.execute("INSERT INTO groups_ (name, aliases, embedding) VALUES (%s, %s, %s)", (name, json.dumps(aliases), vec))
            gids[name] = cur.lastrowid
            cur.executemany("INSERT INTO group_members (group_id, person_id) VALUES (%s, %s)",
                            [(gids[name], ids[m]) for m in members])
    print(f"  groups: {', '.join(gids)}")

    # ---------- venues ----------
    vecs = try_embed([f"{v[0]} · {v[1]} · {v[6]}" for v in VENUES])
    vids: dict[str, int] = {}
    with cursor() as cur:
        for (name, kind, (lat, lng), price, parking, indoor, desc), vec in zip(VENUES, vecs):
            cur.execute(
                "INSERT INTO venues (name, kind, lat, lng, price_pp, parking, indoor, description, embedding)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (name, kind, lat, lng, price, parking, indoor, desc, vec))
            vids[name] = cur.lastrowid
    print(f"  venues: {len(vids)}")

    # ---------- calendars (busy blocks, today .. 8 days out) ----------
    wk = weekend(today)
    rows = []
    for i, name in enumerate(ids):
        free = {wk[day]: FREE[day][name] for day in FREE if name in FREE[day]}
        rows += [(ids[name], s, e, label) for s, e, label in busy_blocks(free, today, today + timedelta(days=8), i)]
    with cursor() as cur:
        cur.executemany("INSERT INTO availability (person_id, starts_at, ends_at, busy_label) VALUES (%s,%s,%s,%s)", rows)
    print(f"  availability: {len(rows)} busy blocks; all of Friday crew free {wk['sat']} 14:00-18:00")

    # ---------- a past confirmed meetup (bowling), so the planner can learn real costs ----------
    past = today - timedelta(days=10)
    p_start, p_end = datetime.combine(past, time(19)), datetime.combine(past, time(21))
    with cursor() as cur:
        cur.execute("INSERT INTO meetups (group_id, title, status, venue_id, starts_at, ends_at)"
                    " VALUES (%s, %s, 'confirmed', %s, %s, %s)",
                    (gids["Friday crew"], "Friday crew meetup", vids["Lucky Lanes Bowling"], p_start, p_end))
        past_meetup = cur.lastrowid
        cur.execute("INSERT INTO meetup_options (meetup_id, option_no, venue_id, starts_at, ends_at, per_person, weather, score, why)"
                    " VALUES (%s, 1, %s, %s, %s, %s, %s, 0, %s)",
                    (past_meetup, vids["Lucky Lanes Bowling"], p_start, p_end, "[]", json.dumps({"rain_prob": 0, "temp_c": 15, "source": "seed"}),
                     "Seeded past meetup"))

    # ---------- expenses ----------
    apt, crew = [me, ids["Sam"], ids["Priya"]], [me, ids["Sam"], ids["Priya"], ids["Alex Chen"]]
    last_wed = dates.resolve_day({"weekday": "wed"}, today)
    d = lambda n: today - timedelta(days=n)
    # (day, amount, description, merchant, category, payer, participants, group, meetup)
    E = [
        (last_wed, "20.00", "cab", "Yellow Cab", "transport", me, None, None, None),
        (d(2), "14.50", "Uber to work", "Uber", "transport", me, None, None, None),
        (d(5), "18.20", "Lyft home", "Lyft", "transport", me, None, None, None),
        (d(9), "11.75", "Uber to the gym", "Uber", "transport", me, None, None, None),
        (d(13), "22.40", "Lyft to the airport", "Lyft", "transport", me, None, None, None),
        (d(17), "16.00", "Uber downtown", "Uber", "transport", me, None, None, None),
        (d(1), "12.40", "tomatoes and bread", "Trader Joe's", "groceries", me, None, None, None),
        (d(3), "13.80", "burrito bowl", "Chipotle", "dining", me, None, None, None),
        (d(4), "16.50", "movie ticket", "AMC", "entertainment", me, None, None, None),
        (d(6), "11.99", "Spotify", "Spotify", "subscriptions", me, None, None, None),
        (d(8), "23.10", "cold medicine", "CVS", "health", me, None, None, None),
        (d(11), "89.00", "running shoes", "Nike", "shopping", me, None, None, None),
        (d(12), "15.49", "Netflix", "Netflix", "subscriptions", me, None, None, None),
        (d(15), "45.00", "gym membership", "Mission Cliffs", "health", me, None, None, None),
        (d(19), "5.75", "coffee", "Philz Coffee", "dining", me, None, None, None),
        (d(6), "64.20", "groceries", "Safeway", "groceries", me, apt, "Apt 4B", None),
        (d(10), "27.90", "cleaning supplies", "Target", "household", ids["Sam"], apt, "Apt 4B", None),
        (d(14), "75.00", "internet bill", "Comcast", "utilities", me, apt, "Apt 4B", None),
        (d(18), "132.45", "Costco run", "Costco", "groceries", ids["Priya"], apt, "Apt 4B", None),
        (d(20), "96.30", "electricity bill", "PG&E", "utilities", ids["Priya"], apt, "Apt 4B", None),
        (past, "136.00", "bowling night", "Lucky Lanes Bowling", "entertainment", me, crew, "Friday crew", past_meetup),
        (d(16), "88.00", "ramen dinner", "Tonkotsu Corner", "dining", ids["Alex Chen"], crew, "Friday crew", None),
        (d(3), "72.00", "karaoke drinks", "Hayes Karaoke", "dining", ids["Sam"], crew, "Friday crew", None),
        (d(7), "54.00", "dinner", "Hayes Dumpling House", "dining", me, [me, ids["Alex Park"]], None, None),
        (d(12), "38.50", "brunch", "Steep Coffee Co.", "dining", me, [me, ids["Alex Chen"]], None, None),
    ]
    made = []
    for day, amount, desc, merchant, cat, payer, people, group, meetup in E:
        r = ledger.create_expense(amount=amount, description=desc, merchant=merchant, category=cat, spent_on=day,
                                  payer_id=payer, participant_ids=people, group_id=gids.get(group), meetup_id=meetup)
        made.append(r["expense"]["id"])
    r = ledger.record_settlement(amount="15.00", from_id=ids["Sam"], group_id=gids["Apt 4B"], spent_on=d(2))
    made.append(r["expense"]["id"])
    with cursor() as cur:
        cur.execute(f"UPDATE expenses SET is_demo = TRUE WHERE id IN ({','.join(['%s'] * len(made))})", made)
    print(f"  expenses: {len(made)} (incl. $20 cab on {last_wed}, 1 settlement), all is_demo")

    print("\nBalances (positive = is owed):")
    for p in ledger.balances():
        print(f"  {p['name']:<10} {Decimal(p['net']):>9}")


if __name__ == "__main__":
    main()
