"""Populate a freshly reset database with people, availability, venues and demo history."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src import config
from src.core.expenses.splits import build_shares
from src.db.s2_client import cursor, to_vector, transaction
from src.model.embeddings import embed, expense_embed_text

PEOPLE = [
    ("You", ["me", "I"], 37.7749, -122.4194, 45, "transit", ["food", "hiking", "music"]),
    ("Sam", ["Sammy", "S"], 37.7694, -122.4862, 40, "drive", ["bowling", "ramen", "music"]),
    ("Priya", ["P"], 37.7842, -122.4071, 35, "transit", ["art", "food", "escape rooms"]),
    ("Alex Chen", ["Chen", "Alex C"], 37.7599, -122.4148, 30, "walk", ["parks", "coffee", "games"]),
    ("Alex Park", ["Park", "Alex P"], 37.8008, -122.4367, 25, "transit", ["food", "movies", "music"]),
]
VENUES = [
    ("Juniper Cafe", "cafe", 37.776, -122.424, 18, 0, True, "Relaxed neighborhood cafe with pastries and coffee"),
    ("Lucky Strike Bowling", "bowling", 37.769, -122.414, 32, 8, True, "Bowling lanes and arcade games"),
    ("Dolores Park Picnic", "park", 37.7596, -122.4269, 8, 0, False, "Outdoor park picnic with skyline views"),
    ("Marufuku Ramen", "restaurant", 37.785, -122.433, 24, 0, True, "Casual ramen restaurant with shared tables"),
    ("EscapeSF", "activity", 37.787, -122.407, 38, 0, True, "Team escape room puzzles"),
    ("The Cheap Shot", "bar", 37.771, -122.411, 22, 0, True, "Affordable neighborhood bar with games"),
    ("Prime House", "restaurant", 37.791, -122.399, 95, 25, True, "Upscale steakhouse with premium menu"),
    ("Bay Ridge Retreat", "outdoors", 38.45, -122.52, 20, 10, False, "Scenic outdoor retreat far from downtown"),
    ("Civic Center Cinema", "movie", 37.779, -122.415, 28, 12, True, "Movie theater with comfortable seats"),
    ("Mission Craft Hall", "food hall", 37.761, -122.421, 27, 5, True, "Food hall with many cuisines"),
    ("Golden Gate Mini Golf", "activity", 37.769, -122.478, 26, 4, False, "Outdoor mini golf course"),
    ("Soma Board Game Cafe", "cafe", 37.778, -122.405, 20, 0, True, "Board games, snacks and coffee"),
]


def dt(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour))


def main() -> None:
    # Embed people and venues in batches. Store only vectors, never call the model per row.
    vectors = embed([" ".join((name, *aliases)) for name, aliases, *_ in PEOPLE] + [
        f"{name} · {kind} · {description}" for name, kind, _, _, _, _, _, description in VENUES
    ])
    today = datetime.now(ZoneInfo(config.TZ)).date()
    with transaction() as cur:
        cur.execute("DELETE FROM meetup_votes")
        cur.execute("DELETE FROM meetup_options")
        cur.execute("DELETE FROM meetups")
        cur.execute("DELETE FROM availability")
        cur.execute("DELETE FROM venues")
        cur.execute("DELETE FROM expense_shares")
        cur.execute("DELETE FROM expenses")
        cur.execute("DELETE FROM group_members")
        cur.execute("DELETE FROM groups_")
        cur.execute("DELETE FROM people")
        people_ids = {}
        for i, (name, aliases, lat, lng, travel, mode, interests) in enumerate(PEOPLE):
            cur.execute(
                "INSERT INTO people (name,is_me,aliases,embedding,home_lat,home_lng,meetup_budget,max_travel_min,travel_mode,interests) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, i == 0, __import__("json").dumps(aliases), to_vector(vectors[i]), lat, lng,
                 Decimal(25 + i * 8), travel, mode, __import__("json").dumps(interests)),
            )
            people_ids[name] = cur.lastrowid
        group_ids = {}
        for name, aliases, members in [
            ("Apt 4B", ["roommates", "roomies"], ["You", "Sam", "Priya"]),
            ("Friday crew", ["the crew", "friends", "the four of us"], ["You", "Sam", "Priya", "Alex Chen"]),
        ]:
            cur.execute("INSERT INTO groups_ (name,aliases) VALUES (%s,%s)", (name, __import__("json").dumps(aliases)))
            gid = cur.lastrowid
            group_ids[name] = gid
            cur.executemany("INSERT INTO group_members (group_id,person_id) VALUES (%s,%s)", [(gid, people_ids[p]) for p in members])
        venue_ids = {}
        offset = len(PEOPLE)
        for i, venue in enumerate(VENUES):
            name, kind, lat, lng, price, parking, indoor, description = venue
            cur.execute(
                "INSERT INTO venues (name,kind,lat,lng,price_pp,parking,indoor,description,embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, kind, lat, lng, price, parking, indoor, description, to_vector(vectors[offset + i])),
            )
            venue_ids[name] = cur.lastrowid

        # Busy blocks carry intentionally private labels. A common Saturday window remains open for all four.
        for i, (person, *_rest) in enumerate(PEOPLE[:4]):
            pid = people_ids[person]
            for delta in range(7):
                day = today + timedelta(days=delta)
                if day.weekday() == 5:
                    continue
                hour = 9 + (i + delta) % 6
                cur.execute("INSERT INTO availability (person_id,starts_at,ends_at,busy_label) VALUES (%s,%s,%s,%s)",
                            (pid, dt(day, hour), dt(day, hour + 2), ["Dentist", "Work", "Class", "Appointment"][i]))
        # This Sunday window has one person busy, so it cannot be selected for the full group.
        sunday = today + timedelta(days=(6 - today.weekday()) % 7)
        cur.execute("INSERT INTO availability (person_id,starts_at,ends_at,busy_label) VALUES (%s,%s,%s,%s)",
                    (people_ids["Priya"], dt(sunday, 14), dt(sunday, 17), "Private appointment"))

        # Past confirmed meetup and two linked expenses provide preference-learning examples.
        past_day = today - timedelta(days=14)
        cur.execute("INSERT INTO meetups (group_id,title,status,venue_id,starts_at,ends_at) VALUES (%s,%s,'confirmed',%s,%s,%s)",
                    (group_ids["Friday crew"], "Old Friday dinner", venue_ids["Marufuku Ramen"], dt(past_day, 18), dt(past_day, 20)))
        old_meetup = cur.lastrowid
        for description, amount, category, participants, payer in [
            ("ramen dinner", Decimal("72.00"), "dining", ["You", "Sam", "Priya", "Alex Chen"], "You"),
            ("bowling after dinner", Decimal("48.00"), "entertainment", ["You", "Sam", "Priya", "Alex Chen"], "Sam"),
        ]:
            _insert_demo(cur, description, amount, category, past_day, participants, payer, people_ids, group_ids["Friday crew"], old_meetup)
        # 28 more everyday demo rows, including a $20 cab last Wednesday and semantic ride examples.
        demos = [
            ("cab", "20.00", "transport", (today.weekday() - 2) % 7 or 7), ("Uber to work", "18.50", "transport", 2),
            ("Lyft home", "22.00", "transport", 4), ("Uber airport ride", "41.00", "transport", 12),
            ("groceries", "64.20", "groceries", 1), ("coffee", "8.50", "dining", 0),
            ("Thai takeout", "31.40", "dining", 3), ("bus pass", "25.00", "transport", 7),
            ("Trader Joe's", "53.12", "groceries", 5), ("movie tickets", "34.00", "entertainment", 6),
            ("parking", "12.00", "transport", 8), ("electric bill", "86.00", "utilities", 10),
            ("pizza", "28.75", "dining", 11), ("pharmacy", "17.99", "health", 13),
            ("Lyft to dinner", "16.30", "transport", 15), ("cleaning supplies", "26.10", "household", 16),
            ("museum", "24.00", "entertainment", 17), ("gas", "45.00", "transport", 18),
            ("lunch", "19.25", "dining", 20), ("groceries", "72.44", "groceries", 21),
            ("Uber downtown", "14.75", "transport", 22), ("concert", "59.00", "entertainment", 23),
            ("coffee beans", "16.50", "groceries", 24), ("dinner", "42.00", "dining", 25),
            ("train fare", "11.25", "transport", 26), ("household items", "38.00", "household", 27),
            ("subscription", "12.99", "subscriptions", 28), ("park snacks", "14.00", "dining", 29),
        ]
        for desc, amount, category, ago in demos:
            day = today - timedelta(days=ago)
            _insert_demo(cur, desc, Decimal(amount), category, day, ["You"], "You", people_ids, None, None)
    print("Seeded 5 people, 2 groups, availability, 12 venues and 30 demo expenses")


def _insert_demo(cur, description, amount, category, day, participants, payer, people_ids, group_id, meetup_id):
    vec = to_vector(embed([expense_embed_text(description, category, None)])[0])
    cur.execute("INSERT INTO expenses (spent_on,amount,description,category,group_id,meetup_id,status,is_demo,embedding) VALUES (%s,%s,%s,%s,%s,%s,'logged',TRUE,%s)",
                (day, amount, description, category, group_id, meetup_id, vec))
    eid = cur.lastrowid
    shares = build_shares(amount, people_ids[payer], [people_ids[p] for p in participants])
    cur.executemany("INSERT INTO expense_shares (expense_id,person_id,paid,owed) VALUES (%s,%s,%s,%s)",
                    [(eid, s.person_id, s.paid, s.owed) for s in shares])


if __name__ == "__main__":
    main()
