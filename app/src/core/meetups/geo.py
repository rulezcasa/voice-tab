"""Distance, travel time and travel cost. Pure Python, no database, no models."""
import math
from decimal import Decimal

EARTH_MI = 3958.8
KM_PER_MI = 1.609344

# mode -> (average speed in mph, cost per mile one way, flat fare one way)
MODES = {
    "walk":    (3.0,  Decimal("0.00"), Decimal("0.00")),
    "bike":    (10.0, Decimal("0.00"), Decimal("0.00")),
    "transit": (12.0, Decimal("0.00"), Decimal("2.75")),
    "drive":   (18.0, Decimal("0.40"), Decimal("0.00")),
}
OVERHEAD_MIN = 5          # getting out the door, walking to the stop, finding the place
DEFAULT_RADIUS_MI = {"walk": 2.0, "bike": 5.0, "transit": 6.0, "drive": 15.0}
CENT = Decimal("0.01")


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(h))


def midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Average of the points. Fine at city scale (no antimeridian handling needed)."""
    if not points:
        raise ValueError("midpoint of no points")
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def within(a: tuple[float, float], b: tuple[float, float], miles: float) -> bool:
    return haversine_mi(a, b) <= miles


def travel(origin: tuple[float, float], dest: tuple[float, float], mode: str,
           parking: Decimal = Decimal("0"), group_size: int = 1) -> tuple[int, Decimal, float]:
    """(minutes one way, round-trip cost, miles one way). Parking is split across the group."""
    speed, per_mile, flat = MODES.get(mode, MODES["transit"])
    miles = haversine_mi(origin, dest)
    minutes = int(round(miles / speed * 60)) + OVERHEAD_MIN
    cost = (Decimal(str(miles)) * per_mile + flat) * 2
    if mode == "drive" and parking:
        cost += Decimal(str(parking)) / max(group_size, 1)
    return minutes, cost.quantize(CENT), miles


def coarse(lat: float, lng: float) -> tuple[float, float]:
    """Round to 2 decimals (~1 km): enough to find a fair midpoint, not enough to find a house."""
    return (round(lat, 2), round(lng, 2))
