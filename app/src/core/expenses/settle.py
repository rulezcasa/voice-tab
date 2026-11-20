"""Who owes whom, and the fewest transfers that settle everyone up. Pure Python, no database.

Input is share rows (expense_id, person_id, paid, owed), settlements included: "Sam paid me back"
is stored as Sam paid / me owed, so it cancels Sam's debt to me naturally.
"""
from collections import defaultdict
from decimal import Decimal

ZERO = Decimal("0.00")


def _greedy(nets: dict[int, Decimal]) -> list[tuple[int, int, Decimal]]:
    """(from, to, amount) transfers that zero every net. Biggest debtor pays biggest creditor first."""
    debtors = sorted(((p, -n) for p, n in nets.items() if n < 0), key=lambda x: -x[1])
    creditors = sorted(((p, n) for p, n in nets.items() if n > 0), key=lambda x: -x[1])
    out, i, j = [], 0, 0
    debtors, creditors = [list(d) for d in debtors], [list(c) for c in creditors]
    while i < len(debtors) and j < len(creditors):
        amt = min(debtors[i][1], creditors[j][1])
        if amt > 0:
            out.append((debtors[i][0], creditors[j][0], amt))
        debtors[i][1] -= amt
        creditors[j][1] -= amt
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return out


def pairwise(shares: list[dict]) -> list[dict]:
    """Net debts between pairs: [{"from": person_id, "to": person_id, "amount": Decimal}], amount > 0.

    Within each expense, people who paid more than their share are owed by those who paid less.
    Debts in both directions between the same two people are netted out.
    """
    by_expense: dict[int, dict[int, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for s in shares:
        by_expense[s["expense_id"]][s["person_id"]] += Decimal(str(s["paid"])) - Decimal(str(s["owed"]))

    debt: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)  # (a, b) with a < b: + means a owes b
    for nets in by_expense.values():
        for frm, to, amt in _greedy(dict(nets)):
            a, b = sorted((frm, to))
            debt[(a, b)] += amt if frm == a else -amt

    out = []
    for (a, b), amt in sorted(debt.items()):
        if amt > 0:
            out.append({"from": a, "to": b, "amount": amt})
        elif amt < 0:
            out.append({"from": b, "to": a, "amount": -amt})
    return out


def suggest_transfers(nets: dict[int, Decimal]) -> list[dict]:
    """Fewest-ish transfers that bring every balance to zero (positive net = is owed)."""
    clean = {p: Decimal(str(n)) for p, n in nets.items() if Decimal(str(n)) != 0}
    if sum(clean.values(), ZERO) != 0:
        raise ValueError(f"balances don't sum to zero: {sum(clean.values(), ZERO)}")
    return [{"from": f, "to": t, "amount": a} for f, t, a in _greedy(clean)]
