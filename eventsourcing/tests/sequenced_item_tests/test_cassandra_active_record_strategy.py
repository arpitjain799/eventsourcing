from eventsourcing.infrastructure.cassandra.activerecords import CassandraActiveRecordStrategy, \
    CqlIntegerSequencedItem, CqlSnapshot, CqlTimestampSequencedItem
from eventsourcing.infrastructure.sequenceditem import SequencedItem
from eventsourcing.tests.datastore_tests.test_cassandra import CassandraDatastoreTestCase
from eventsourcing.tests.sequenced_item_tests.base import IntegerSequencedItemTestCase, \
    SimpleSequencedItemteratorTestCase, ThreadedSequencedItemIteratorTestCase, TimestampSequencedItemTestCase, \
    WithActiveRecordStrategies


def construct_integer_sequenced_active_record_strategy():
    return CassandraActiveRecordStrategy(
        active_record_class=CqlIntegerSequencedItem,
        sequenced_item_class=SequencedItem,
    )


def construct_timestamp_sequenced_active_record_strategy():
    return CassandraActiveRecordStrategy(
        active_record_class=CqlTimestampSequencedItem,
        sequenced_item_class=SequencedItem,
    )


def construct_snapshot_active_record_strategy():
    return CassandraActiveRecordStrategy(
        active_record_class=CqlSnapshot,
        sequenced_item_class=SequencedItem,
    )


class TestCassandraActiveRecordStrategyWithIntegerSequences(CassandraDatastoreTestCase,
                                                            IntegerSequencedItemTestCase):
    def construct_active_record_strategy(self):
        return construct_integer_sequenced_active_record_strategy()


class TestCassandraActiveRecordStrategyWithTimestampSequences(CassandraDatastoreTestCase,
                                                              TimestampSequencedItemTestCase):
    def construct_active_record_strategy(self):
        return construct_timestamp_sequenced_active_record_strategy()


class WithCassandraActiveRecordStrategies(CassandraDatastoreTestCase, WithActiveRecordStrategies):
    def construct_integer_sequenced_active_record_strategy(self):
        return construct_integer_sequenced_active_record_strategy()

    def construct_timestamp_sequenced_active_record_strategy(self):
        return construct_timestamp_sequenced_active_record_strategy()

    def construct_snapshot_active_record_strategy(self):
        return construct_snapshot_active_record_strategy()


class TestSimpleSequencedItemIteratorWithCassandra(WithCassandraActiveRecordStrategies,
                                                   SimpleSequencedItemteratorTestCase):
    pass


class TestThreadedSequencedItemIteratorWithCassandra(WithCassandraActiveRecordStrategies,
                                                     ThreadedSequencedItemIteratorTestCase):
    pass