"""Pure-Python helpers for explaining and simplifying who owes whom."""
from collections import defaultdict
from decimal import Decimal


def pairwise(expenses_with_shares: list[dict]) -> list[dict]:
    """Net each payer's claims against each participant's owed share across expenses.

    Each expense is expected to contain ``shares`` rows with ``person_id``, ``paid``
    and ``owed`` values, as returned by ledger.get_expense().
    """
    amounts: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for expense in expenses_with_shares:
        shares = expense.get("shares", [])
        payers = [(s["person_id"], Decimal(str(s["paid"]))) for s in shares if Decimal(str(s["paid"])) > 0]
        owed = [(s["person_id"], Decimal(str(s["owed"]))) for s in shares if Decimal(str(s["owed"])) > 0]
        for payer, paid in payers:
            for person, share in owed:
                if person != payer:
                    amounts[(person, payer)] += share

    result = []
    pairs = {tuple(sorted(pair)) for pair in amounts}
    for a, b in sorted(pairs):
        a_to_b = amounts[(a, b)]
        b_to_a = amounts[(b, a)]
        net = a_to_b - b_to_a
        if net > 0:
            result.append({"from": a, "to": b, "amount": net})
        elif net < 0:
            result.append({"from": b, "to": a, "amount": -net})
    return result


def suggest_transfers(nets: dict[int, Decimal]) -> list[dict]:
    """Greedily match the largest debtor and creditor until balances reach zero."""
    debtors = [[pid, -Decimal(str(net))] for pid, net in nets.items() if Decimal(str(net)) < 0]
    creditors = [[pid, Decimal(str(net))] for pid, net in nets.items() if Decimal(str(net)) > 0]
    transfers = []
    while debtors and creditors:
        debtors.sort(key=lambda item: (-item[1], item[0]))
        creditors.sort(key=lambda item: (-item[1], item[0]))
        debtor, debt = debtors[0]
        creditor, credit = creditors[0]
        amount = min(debt, credit)
        transfers.append({"from": debtor, "to": creditor, "amount": amount})
        debtors[0][1] -= amount
        creditors[0][1] -= amount
        if debtors[0][1] == 0:
            debtors.pop(0)
        if creditors[0][1] == 0:
            creditors.pop(0)
    return transfers
