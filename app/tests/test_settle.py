"""Who-owes-whom tests, no database. Run from app/:  python -m unittest tests.test_settle -v"""
import unittest
from decimal import Decimal as D

from src.core.expenses.settle import pairwise, suggest_transfers

ME, SAM, PRIYA, ALEX = 1, 2, 3, 4


def share(e, p, paid, owed):
    return {"expense_id": e, "person_id": p, "paid": D(paid), "owed": D(owed)}


class Pairwise(unittest.TestCase):
    def test_equal_split(self):
        # I paid 40 for 3: Sam and Priya each owe me their share
        s = [share(1, ME, "40", "13.34"), share(1, SAM, "0", "13.33"), share(1, PRIYA, "0", "13.33")]
        self.assertEqual(pairwise(s), [{"from": SAM, "to": ME, "amount": D("13.33")},
                                       {"from": PRIYA, "to": ME, "amount": D("13.33")}])

    def test_debts_net_out_between_two_people(self):
        s = [share(1, ME, "40", "20"), share(1, SAM, "0", "20"),      # Sam owes me 20
             share(2, SAM, "30", "15"), share(2, ME, "0", "15")]      # I owe Sam 15
        self.assertEqual(pairwise(s), [{"from": SAM, "to": ME, "amount": D("5")}])

    def test_settlement_clears_debt(self):
        s = [share(1, ME, "26.66", "13.33"), share(1, SAM, "0", "13.33"),
             share(2, SAM, "13.33", "0"), share(2, ME, "0", "13.33")]  # "Sam paid me back 13.33"
        self.assertEqual(pairwise(s), [])

    def test_lunch_for_four(self):
        s = [share(1, ME, "48", "12")] + [share(1, p, "0", "12") for p in (SAM, PRIYA, ALEX)]
        self.assertEqual(sorted(d["from"] for d in pairwise(s)), [SAM, PRIYA, ALEX])
        self.assertTrue(all(d["amount"] == D("12") and d["to"] == ME for d in pairwise(s)))

    def test_personal_expense_owes_nobody(self):
        self.assertEqual(pairwise([share(1, ME, "20", "20")]), [])


class Transfers(unittest.TestCase):
    def test_fewest_transfers_zero_everyone(self):
        nets = {ME: D("30"), SAM: D("-10"), PRIYA: D("-20"), ALEX: D("0")}
        t = suggest_transfers(nets)
        self.assertEqual(t, [{"from": PRIYA, "to": ME, "amount": D("20")}, {"from": SAM, "to": ME, "amount": D("10")}])

    def test_chain_collapses(self):
        # Sam owes me 10, I owe Priya 10 -> Sam pays Priya directly
        self.assertEqual(suggest_transfers({SAM: D("-10"), ME: D("0"), PRIYA: D("10")}),
                         [{"from": SAM, "to": PRIYA, "amount": D("10")}])

    def test_rejects_unbalanced(self):
        with self.assertRaises(ValueError):
            suggest_transfers({ME: D("5"), SAM: D("-4")})


if __name__ == "__main__":
    unittest.main()
