"""AI-104: negation-safe approval classification (audit C6).

The dangerous direction is false-affirmative: any test where a refusal or
acknowledgment classifies as AFFIRMATIVE is an instant failure.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from amancore.channels.intent_rules import (  # noqa: E402
    AFFIRMATIVE, HUMAN_REQUEST, NEGATIVE, UNCERTAIN, classify_approval,
    summary_question_pending)

SUMMARY = "هذا ملخص كل شيء — هل أنت موافق؟"


class ApprovalClassification(unittest.TestCase):
    # ---- explicit consent -------------------------------------------------
    def test_affirmatives(self):
        for t in ("موافق", "نعم", "نعم موافق", "تم، موافق", "approved",
                  "موافق شكراً", "أوافق تماماً"):
            self.assertEqual(classify_approval(t, SUMMARY), AFFIRMATIVE, t)

    # ---- the audit C6 killers ---------------------------------------------
    def test_negations_never_approve(self):
        for t in ("لست موافق على السعر", "لا", "غير موافق", "لا أريد",
                  "لا، أوكي", "ما أوافق", "not approved", "لا اوك"):
            self.assertEqual(classify_approval(t, SUMMARY), NEGATIVE, t)

    # ---- acknowledgments are NOT consent ----------------------------------
    def test_weak_acks_uncertain(self):
        for t in ("أوكي شكراً", "اوكي", "ok", "تمام", "حسناً"):
            self.assertEqual(classify_approval(t, SUMMARY), UNCERTAIN, t)

    # ---- echo-question -----------------------------------------------------
    def test_echo_question_not_consent(self):
        self.assertEqual(classify_approval("موافق؟", SUMMARY), UNCERTAIN)

    # ---- human requests ----------------------------------------------------
    def test_human_requests(self):
        for t in ("أريد التحدث مع شخص", "أريد موظف", "ابغى انسان",
                  "talk to a real person"):
            self.assertEqual(classify_approval(t, SUMMARY), HUMAN_REQUEST, t)

    # ---- noise / unrelated -------------------------------------------------
    def test_unrelated_is_uncertain(self):
        for t in ("كم السعر؟", "وش تقدمون؟", ""):
            self.assertEqual(classify_approval(t, SUMMARY), UNCERTAIN, t)

    def test_negator_far_from_strong_still_negative(self):
        self.assertEqual(classify_approval("لا في الوقت الحالي موافق بعدين",
                                           SUMMARY), NEGATIVE)

    def test_late_strong_after_old_negation(self):
        """SAFETY BIAS (C6): any strong term after a negation is consumed by it.
        A genuinely flipped customer will simply be asked to confirm again —
        a false handover is strictly worse than a missed one."""
        self.assertEqual(
            classify_approval("بالبداية لا، بس الحين صرت موافق", SUMMARY),
            NEGATIVE)

    # ---- prev_out gate helper ---------------------------------------------
    def test_summary_question_pending(self):
        self.assertTrue(summary_question_pending(SUMMARY))
        self.assertTrue(summary_question_pending("ملخص... هل هذا صحيح؟"))
        self.assertFalse(summary_question_pending("شكراً لتواصلك"))
        self.assertFalse(summary_question_pending(""))


if __name__ == "__main__":
    unittest.main()
