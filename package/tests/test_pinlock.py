import unittest
from tvwcs.pinlock import PinGate, check_pin, make_hash, valid_hash, valid_pin
from tvwcs.ownership import WindowOwners


class PinTests(unittest.TestCase):
    def test_pin_shape(self):
        for ok in ("1234", "00000", "12345678"):
            self.assertTrue(valid_pin(ok), ok)
        for bad in ("", "123", "123456789", "12a4", "12 34", None):
            self.assertFalse(valid_pin(bad), bad)

    def test_hash_and_check(self):
        h = make_hash("4321")
        self.assertTrue(valid_hash(h))
        self.assertRegex(
            h, r"^[0-9a-f]{32}\$[0-9a-f]+$"
        )  # only salt$digest in hex: the PIN itself is not kept (random hex can contain "4321")
        self.assertTrue(check_pin("4321", h))
        self.assertFalse(check_pin("4322", h))
        self.assertFalse(check_pin("", h))
        self.assertNotEqual(h, make_hash("4321"))  # salted
        with self.assertRaises(ValueError):
            make_hash("12")

    def test_bad_stored_values_never_match(self):
        for stored in ("", "1234", "zz$zz", None):
            self.assertFalse(check_pin("1234", stored))

    def test_gate_locks_after_repeated_failures_then_recovers(self):
        now = [100.0]
        gate = PinGate(limit=3, lockout=30, clock=lambda: now[0])
        h = make_hash("1111")
        self.assertEqual(gate.attempt("p", "0000", h), ("wrong", 0))
        self.assertEqual(gate.attempt("p", "0000", h), ("wrong", 0))
        status, wait = gate.attempt("p", "0000", h)
        self.assertEqual((status, wait), ("locked", 30))
        self.assertEqual(gate.attempt("p", "1111", h)[0], "locked")  # even the right PIN waits
        now[0] += 31
        self.assertEqual(gate.attempt("p", "1111", h), ("ok", 0))

    def test_gate_counts_per_profile_and_resets_on_success(self):
        gate = PinGate(limit=2, lockout=30, clock=lambda: 0)
        a = make_hash("1111")
        b = make_hash("2222")
        gate.attempt("a", "0", a)
        self.assertEqual(gate.attempt("b", "2222", b), ("ok", 0))
        self.assertEqual(gate.attempt("a", "1111", a), ("ok", 0))
        self.assertEqual(gate.attempt("a", "9999", a), ("wrong", 0))


class OwnershipTests(unittest.TestCase):
    def win(self, i):
        return {"con_id": i}

    def test_new_windows_are_claimed_by_the_launching_profile(self):
        o = WindowOwners()
        o.claim({1, 2}, [self.win(1), self.win(2), self.win(3)], "kids")
        self.assertEqual(o.owner(3), "kids")
        self.assertIsNone(o.owner(1))

    def test_a_claimed_window_is_not_reassigned(self):
        o = WindowOwners()
        o.claim(set(), [self.win(5)], "a")
        o.claim(set(), [self.win(5)], "b")
        self.assertEqual(o.owner(5), "a")

    def test_accept_filter_skips_unrelated_windows(self):
        o = WindowOwners()
        o.claim(set(), [self.win(1), self.win(2)], "p", accept=lambda w: w["con_id"] == 2)
        self.assertEqual((o.owner(1), o.owner(2)), (None, "p"))

    def test_closed_windows_are_forgotten(self):
        o = WindowOwners()
        o.claim(set(), [self.win(1), self.win(2)], "p")
        o.forget_closed([self.win(2)])
        self.assertEqual((o.owner(1), o.owner(2)), (None, "p"))


if __name__ == "__main__":
    unittest.main()
