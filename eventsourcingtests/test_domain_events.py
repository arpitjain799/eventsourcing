import unittest
from unittest import mock

from eventsourcing.domain.model.events import subscribe, publish, unsubscribe
from eventsourcing.domain.model.example import Example


class TestEvents(unittest.TestCase):

    def test_events(self):
        event = Example.Event(a=1, b=2)

        # Check constructor keyword args lead to read-only attributes.
        self.assertEqual(1, event.a)
        self.assertEqual(2, event.b)
        self.assertRaises(AttributeError, getattr, event, 'c')
        self.assertRaises(AttributeError, setattr, event, 'c', 3)

        # Check domain event has auto-generated timestamp.
        self.assertIsInstance(event.timestamp, float)

        # Check timestamp value can be given to domain events.
        self.assertEqual(3, Example.Event(a=1, b=2, timestamp=3).timestamp)

    def test_publish_subscribe(self):
        # Check subscribing event handlers with predicates.
        # - when predicate is True, handler should be called
        event = mock.Mock()
        predicate = mock.Mock()
        handler = mock.Mock()
        subscribe(event_predicate=predicate, subscriber=handler)
        publish(event)
        predicate.assert_called_once_with(event)
        handler.assert_called_once_with(event)

        # - when predicate is False, handler should NOT be called
        predicate = lambda x: False
        handler = mock.Mock()
        subscribe(event_predicate=predicate, subscriber=handler)
        publish(event)
        self.assertEqual(0, handler.call_count)

    def test_unsubscribe(self):
        # - when predicate is True, after unsubscribing, handler should NOT be called
        event = mock.Mock()
        predicate = mock.Mock()
        handler = mock.Mock()
        subscribe(event_predicate=predicate, subscriber=handler)
        unsubscribe(event_predicate=predicate, subscriber=handler)
        publish(event)
        predicate.assert_called_once_with(event)
        self.assertEqual(0, handler.call_count)

    def test_hash(self):
        event1 = Example.Event(a=1, b=2, timestamp=3)
        event2 = Example.Event(a=1, b=2, timestamp=3)
        self.assertEqual(hash(event1), hash(event2))

    def test_equality_comparison(self):
        event1 = Example.Event(a=1, b=2, timestamp=3)
        event2 = Example.Event(a=1, b=2, timestamp=3)
        event3 = Example.Event(a=3, b=2, timestamp=3)
        self.assertEqual(event1, event2)
        self.assertNotEqual(event1, event3)
        self.assertNotEqual(event2, event3)

    def test_repr(self):
        event1 = Example.Event(a=1, b=2, timestamp=3)
        self.assertEqual('Example.Event(a=1, b=2, entity_id=None, timestamp=3)', repr(event1))
