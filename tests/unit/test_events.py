import unittest

from amancore.errors import EventError
from amancore.services.events import (
    CanonicalEvent,
    EventDispatcher,
    IdempotencyStore,
)
from tests.common import TempDirTestCase, make_db


class EventsTest(TempDirTestCase, unittest.TestCase):
    def test_event_validation(self):
        ev = CanonicalEvent(
            event_id="e1", event_type="lead.created", timestamp="2026-01-01T00:00:00+00:00"
        )
        ev.validate()  # ok

    def test_unknown_event_type(self):
        ev = CanonicalEvent(event_id="e1", event_type="nope", timestamp="t")
        with self.assertRaises(EventError):
            ev.validate()

    def test_dispatcher_publish_subscribe(self):
        d = EventDispatcher()
        seen = []
        d.subscribe("lead.created", lambda e: seen.append(e.event_id))
        ev = CanonicalEvent(event_id="e1", event_type="lead.created", timestamp="t")
        d.publish(ev)
        self.assertEqual(seen, ["e1"])

    def test_dispatcher_isolates_handler_error(self):
        d = EventDispatcher()
        seen = []

        def bad(e):
            raise RuntimeError("boom")

        d.subscribe("lead.created", bad)
        d.subscribe("lead.created", lambda e: seen.append(e.event_id))
        d.publish(CanonicalEvent(event_id="e1", event_type="lead.created", timestamp="t"))
        self.assertEqual(seen, ["e1"])
        self.assertEqual(len(d.errors), 1)


class IdempotencyTest(TempDirTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = make_db(self.tmp / "t.db")
        self.store = IdempotencyStore(self.db)

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def test_duplicate_does_not_execute_twice(self):
        self.assertTrue(self.store.store("k1", "send_message", '{"ok":1}'))
        self.assertFalse(self.store.store("k1", "send_message", '{"ok":2}'))
        self.assertEqual(self.store.check("k1"), '{"ok":1}')


if __name__ == "__main__":
    unittest.main()
