"""Hangout ranking and OSM parsing tests, no network. Run from app/:  python -m unittest tests.test_hangout -v"""
import unittest

from src.core import places
from src.core.hangout import HangoutError, HangoutRequest, recommend, search_radius, middle, distance_m

# Two friends ~1.6 km apart in the Mission, SF ([lng, lat])
A = (-122.4194, 37.7599)
B = (-122.4194, 37.7743)
MID = (-122.4194, 37.7671)


def req(minutes=(20, 20), modes=("walk", "walk"), budgets=("30", "30"), kinds=("restaurant",), note=""):
    return HangoutRequest(members=[
        {"person_id": 1, "name": "Nik", "is_me": True, "budget": budgets[0], "minutes": minutes[0], "mode": modes[0], "location": A},
        {"person_id": 2, "name": "Sam Lee", "budget": budgets[1], "minutes": minutes[1], "mode": modes[1], "location": B},
    ], kinds=list(kinds), note=note)


def place(pid, name, lng, lat, subtype="restaurant", kind="restaurant", **tags):
    return {"id": f"osm-node-{pid}", "name": name, "kind": kind, "subtype": subtype, "lng": lng, "lat": lat,
            "address": "1 Test St", "tags": {"name": name, **tags}}


PLACES = [
    place(1, "Middle Tacos", -122.4194, 37.7671, cuisine="mexican"),                    # right in the middle
    place(2, "Near Nik Diner", -122.4194, 37.7605),                                      # next to Nik, far from Sam
    place(3, "Far Away Grill", -122.4500, 37.7900),                                      # nobody reaches it walking
    place(4, "Green Leaf", -122.4190, 37.7680, cuisine="vegan", **{"diet:vegetarian": "yes"}),
    place(5, "Middle Tacos", -122.4196, 37.7672, cuisine="mexican"),                     # same chain, second branch
    place(6, "Pricey Theatre", -122.4194, 37.7671, subtype="theatre", kind="activity"),  # $40 est.
]


def fake_fetch(seen):
    def fetch(lat, lng, radius, kinds, terms=()):
        seen.update(lat=lat, lng=lng, radius=radius, kinds=kinds, terms=terms)
        return PLACES
    return fetch


class FakeLLM:
    """Stands in for src.agents.hangout_llm."""
    def __init__(self, terms=None, picks=None):
        self.terms, self.picks, self.seen = terms, picks, {}

    def search_terms(self, note, kinds):
        self.seen["note"] = note
        return self.terms

    def pick(self, candidates, members, note, n):
        self.seen["candidates"] = [c["id"] for c in candidates]
        return self.picks


class Recommend(unittest.TestCase):
    def test_only_the_search_circle_is_sent(self):
        seen = {}
        recommend(req(), fake_fetch(seen))
        self.assertAlmostEqual(seen["lat"], MID[1], places=4)       # the middle, not anyone's pin
        self.assertAlmostEqual(seen["lng"], MID[0], places=4)
        self.assertEqual(seen["kinds"], ["restaurant"])

    def test_reachable_fair_places_first(self):
        r = recommend(req(), fake_fetch({}))
        names = [p["name"] for p in r["places"]]
        self.assertEqual(names[0], "Middle Tacos")                   # shortest, fairest trip
        self.assertNotIn("Far Away Grill", names)                    # nobody can walk there in 20 min
        self.assertEqual(names.count("Middle Tacos"), 1)             # one branch per chain
        self.assertEqual(r["meeting_point"], list(middle(req().members)))

    def test_someone_out_of_time_drops_the_place(self):
        # Sam only walks 5 min: nothing near Nik works, and the middle (~9 min for Sam) doesn't either
        r = recommend(req(minutes=(20, 5)), fake_fetch({}))
        self.assertEqual(r["places"], [])

    def test_budget_uses_the_smallest(self):
        r = recommend(req(budgets=("60", "10"), kinds=("restaurant", "activity")), fake_fetch({}))
        self.assertEqual(r["places"], [])                            # $25 restaurants and a $40 theatre > $10
        r = recommend(req(budgets=("60", "50"), kinds=("restaurant", "activity")), fake_fetch({}))
        self.assertIn("Pricey Theatre", [p["name"] for p in r["places"]])

    def test_note_boosts_matching_places(self):
        r = recommend(req(note="vegetarian please"), fake_fetch({}))
        self.assertEqual(r["places"][0]["name"], "Green Leaf")
        self.assertIn("vegetarian", r["places"][0]["why"])

    def test_shape_matches_the_ui(self):
        p = recommend(req(), fake_fetch({}))["places"][0]
        self.assertEqual(set(p), {"id", "name", "kind", "location", "address", "price_level", "per_person",
                                  "rating", "minutes", "why"})
        self.assertEqual(set(p["minutes"]), {1, 2})
        self.assertIsInstance(p["per_person"], str)
        self.assertIn(p["price_level"], (1, 2, 3, 4))
        self.assertIn("price estimated", p["why"])

    def test_needs_two_people(self):
        one = HangoutRequest(members=[req().members[0]], kinds=["cafe"])
        with self.assertRaises(HangoutError):
            recommend(one, fake_fetch({}))

    def test_search_radius_covers_every_reachable_place_and_is_capped(self):
        r = req(minutes=(20, 20)).members
        rad = search_radius(r, middle(r))
        # a place both can reach (the middle +/- a bit) is inside; the bound is ~ half distance + 1600 m walk
        self.assertGreater(rad, distance_m(A, MID))
        self.assertLessEqual(search_radius(req(minutes=(120, 120), modes=("drive", "drive")).members, MID), 2000)


class Parse(unittest.TestCase):
    def test_overpass_json(self):
        data = {"elements": [
            {"type": "node", "id": 1, "lat": 37.76, "lon": -122.42,
             "tags": {"name": "Tacos El Gordo", "amenity": "fast_food", "addr:housenumber": "2901", "addr:street": "Mission St"}},
            {"type": "way", "id": 2, "center": {"lat": 37.77, "lon": -122.41},
             "tags": {"name": "Lucky Strike", "leisure": "bowling_alley"}},
            {"type": "node", "id": 3, "lat": 37.0, "lon": -122.0, "tags": {"amenity": "cafe"}},           # no name
            {"type": "node", "id": 4, "lat": 37.0, "lon": -122.0, "tags": {"name": "Bank", "amenity": "bank"}},
        ]}
        got = places.parse(data)
        self.assertEqual([(p["name"], p["kind"], p["subtype"]) for p in got],
                         [("Tacos El Gordo", "restaurant", "fast_food"), ("Lucky Strike", "activity", "bowling_alley")])
        self.assertEqual(got[0]["address"], "2901 Mission St")
        self.assertEqual(got[1]["address"], "No address listed")
        self.assertEqual((got[1]["lat"], got[1]["lng"]), (37.77, -122.41))

    def test_query_is_light_and_capped(self):
        q = places.build_query(37.76, -122.42, 1500, ["cafe"])
        self.assertIn('nw(around:1500,37.760000,-122.420000)["amenity"="cafe"]["name"];', q)  # exact match
        self.assertIn('["amenity"="ice_cream"]', q)
        self.assertNotIn("restaurant", q)
        self.assertNotIn("~", q)                                   # no regex
        self.assertNotIn("nwr(", q)                                # no relations
        self.assertTrue(q.endswith(f"out center tags qt {places.MAX_RESULTS};"))
        self.assertEqual(places.MAX_RESULTS, 60)

    def test_photon_first_then_overpass_backup(self):
        calls = []
        def fake_get(url, timeout, data=None):
            calls.append(url.split("/")[2])
            if "photon" in url:
                raise TimeoutError("photon down")
            return {"elements": [{"type": "node", "id": 9, "lat": 37.76, "lon": -122.42,
                                  "tags": {"name": "Ritual Coffee", "amenity": "cafe"}}]}
        real, places._get_json = places._get_json, fake_get
        places._cache.clear()
        try:
            got = places.nearby(37.76, -122.42, 1000, ["cafe"])
        finally:
            places._get_json = real
        self.assertEqual([p["name"] for p in got], ["Ritual Coffee"])
        self.assertIn("photon.komoot.io", calls)
        self.assertEqual(calls[-1], "overpass-api.de")              # every Photon search failed -> Overpass

    def test_everything_down_is_a_clear_error(self):
        def down(url, timeout, data=None):
            raise TimeoutError("down")
        real, places._get_json = places._get_json, down
        places._cache.clear()
        try:
            with self.assertRaises(places.PlacesError):
                places.nearby(37.7, -122.4, 1000, ["bar"])
        finally:
            places._get_json = real


class Photon(unittest.TestCase):
    def test_parse(self):
        data = {"features": [
            {"geometry": {"coordinates": [-122.4216, 37.7649]},
             "properties": {"osm_type": "N", "osm_id": 11, "osm_key": "amenity", "osm_value": "cafe",
                            "name": "Four Barrel Coffee", "housenumber": "375", "street": "Valencia Street"}},
            {"geometry": {"coordinates": [-122.42, 37.76]},
             "properties": {"osm_type": "N", "osm_id": 12, "osm_key": "amenity", "osm_value": "bank", "name": "Bank"}},
        ]}
        got = places.parse_photon(data, "coffee")
        self.assertEqual(len(got), 1)
        p = got[0]
        self.assertEqual((p["id"], p["name"], p["kind"], p["subtype"]), ("osm-N-11", "Four Barrel Coffee", "cafe", "cafe"))
        self.assertEqual((p["address"], p["lng"], p["lat"], p["found_by"]), ("375 Valencia Street", -122.4216, 37.7649, ["coffee"]))

    def test_searches_put_the_agents_words_first_and_stay_capped(self):
        s = places.photon_searches(["restaurant", "cafe"], [("vegetarian", "restaurant"), ("boba", "bar")])
        self.assertEqual(s[0], ("vegetarian", "amenity:restaurant"))
        self.assertNotIn(("boba", "amenity:bar"), s)                 # 'bar' wasn't a chosen kind
        self.assertIn(("coffee", "amenity:cafe"), s)
        self.assertLessEqual(len(places.photon_searches(list(places.KIND_TAGS), [])), places.PHOTON_MAX_SEARCHES)

    def test_bbox_is_around_the_point(self):
        lo_lng, lo_lat, hi_lng, hi_lat = places.bbox(37.76, -122.42, 1000)
        self.assertTrue(lo_lng < -122.42 < hi_lng and lo_lat < 37.76 < hi_lat)
        self.assertAlmostEqual(hi_lat - lo_lat, 2000 / 111_320, places=5)


class WithModel(unittest.TestCase):
    def test_model_words_reach_the_search(self):
        seen, llm = {}, FakeLLM(terms=[("vegan", "restaurant")])
        recommend(req(note="vegan food"), fake_fetch(seen), llm=llm)
        self.assertEqual(seen["terms"], [("vegan", "restaurant")])

    def test_model_picks_order_and_reason(self):
        llm = FakeLLM(terms=[], picks=[("osm-node-4", "Vegan-friendly and central"), ("osm-node-1", "Tacos for all")])
        r = recommend(req(note="vegan"), fake_fetch({}), llm=llm)
        self.assertEqual(r["picked_by"], "qwen")
        self.assertEqual([p["name"] for p in r["places"]], ["Green Leaf", "Middle Tacos"])
        self.assertTrue(r["places"][0]["why"].startswith("Vegan-friendly and central · "))
        self.assertNotIn("osm-node-3", llm.seen["candidates"])      # unreachable place never offered to the model

    def test_model_failure_falls_back_to_code_ranking(self):
        r = recommend(req(note="vegan"), fake_fetch({}), llm=FakeLLM(terms=None, picks=None))
        self.assertEqual(r["picked_by"], "code")
        self.assertEqual(r["places"][0]["name"], "Green Leaf")       # still boosted by the note via its tags

    def test_invented_place_never_reaches_the_map(self):
        import src.agents.hangout_llm as real_llm
        reply = '{"picks": [{"id": "osm-node-999", "why": "Made up"}, {"id": "osm-node-1", "why": "Real"}]}'
        orig = real_llm._chat
        real_llm._chat = lambda *a, **k: reply
        try:
            cands = [{"id": "osm-node-1", "name": "Middle Tacos", "per_person": 25, "minutes": {1: 9, 2: 9},
                      "found_by": [], "label": "mexican"}]
            got = real_llm.pick(cands, req().members, "", 6)
        finally:
            real_llm._chat = orig
        self.assertEqual(got, [("osm-node-1", "Real")])


if __name__ == "__main__":
    unittest.main()
