"""Who paid and who owes: pure Python, no database, no models."""
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


class SplitError(ValueError):
    """The amounts don't add up. The message is safe to say back to the user."""


@dataclass(frozen=True)
class Share:
    person_id: int
    paid: Decimal
    owed: Decimal


def equal_split(total: Decimal, n: int) -> list[Decimal]:
    """40.00 / 3 -> [13.34, 13.33, 13.33]. Always sums exactly to total."""
    base = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    rem = int((total - base * n) / CENT)  # leftover cents
    shares = [base + CENT if i < rem else base for i in range(n)]
    assert sum(shares) == total, (total, shares)
    return shares


def to_money(v) -> Decimal:
    """'40', 40, 40.0, '40.005' -> Decimal('40.00'/'40.01'). Rejects non-numbers and amounts <= 0."""
    try:
        d = Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise SplitError(f"'{v}' is not an amount")
    if not d.is_finite() or d <= 0:
        raise SplitError(f"amount must be more than 0, got {v}")
    return d


def build_shares(
    amount, payer_id: int, participant_ids: list[int], custom: dict[int, object] | None = None,
) -> list[Share]:
    total = to_money(amount)
    people = list(dict.fromkeys(participant_ids))  # dedupe, keep order
    if not people:
        raise SplitError("nobody to split with")
    if payer_id in people:
        people.remove(payer_id)
        people.insert(0, payer_id)

    custom = {pid: to_money(v) for pid, v in (custom or {}).items()}
    unknown = set(custom) - set(people)
    if unknown:
        raise SplitError(f"custom share for someone not in the split: {sorted(unknown)}")

    left = total - sum(custom.values(), Decimal("0"))
    rest = [p for p in people if p not in custom]
    if left < 0:
        raise SplitError(f"custom shares add up to more than {total}")
    if rest:
        if left == 0:
            raise SplitError("custom shares already cover the full amount, nothing left for the others")
        owed = dict(zip(rest, equal_split(left, len(rest))))
    elif left != 0:
        raise SplitError(f"custom shares add up to {total - left}, not {total}")
    else:
        owed = {}
    owed.update(custom)

    shares = [Share(p, total if p == payer_id else Decimal("0.00"), owed[p]) for p in people]
    if payer_id not in owed:
        shares.insert(0, Share(payer_id, total, Decimal("0.00")))

    assert sum(s.paid for s in shares) == total == sum(s.owed for s in shares), shares
    return shares


def settlement_shares(amount, from_id: int, to_id: int) -> list[Share]:
    """'Sam paid me back 13.33': Sam paid 13.33, I owe 13.33. Both balances move toward 0."""
    if from_id == to_id:
        raise SplitError("someone can't settle up with themselves")
    total = to_money(amount)
    return [Share(from_id, total, Decimal("0.00")), Share(to_id, Decimal("0.00"), total)]
