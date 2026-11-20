from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")


def equal_split(total: Decimal, n: int) -> list[Decimal]:
    """40.00 / 3 -> [13.34, 13.33, 13.33]. Always sums exactly to total."""
    base = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    rem = int((total - base * n) / CENT)  # leftover cents
    shares = [base + CENT if i < rem else base for i in range(n)]
    assert sum(shares) == total, (total, shares)
    return shares
