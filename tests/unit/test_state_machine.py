import unittest

from amancore.errors import AmanCoreError
from amancore.sales.state_machine import can_transition, transition


class StateMachineTest(unittest.TestCase):
    def test_valid_transitions(self):
        self.assertEqual(transition("new", "first_message"), "contacted")
        self.assertEqual(transition("contacted", "message"), "engaged")
        self.assertEqual(transition("engaged", "discovery"), "discovery")
        self.assertEqual(transition("discovery", "qualified"), "qualification")
        self.assertEqual(transition("qualification", "recommended"), "offer_recommended")

    def test_new_to_won_invalid(self):
        with self.assertRaises(AmanCoreError):
            transition("new", "won")

    def test_owner_override(self):
        self.assertEqual(transition("new", "won", owner_override=True), "won")

    def test_can_transition(self):
        self.assertTrue(can_transition("discovery", "qualified"))
        self.assertFalse(can_transition("new", "won"))


if __name__ == "__main__":
    unittest.main()
