from eventsourcing.tests.datastore_tests.test_sqlalchemy import SQLAlchemyDatastoreTestCase
from eventsourcing.tests.sequenced_item_tests.base import IntegerSequencedItemTestCase, \
    SimpleSequencedItemteratorTestCase, ThreadedSequencedItemIteratorTestCase, TimestampSequencedItemTestCase, \
    WithRecordManagers


class WithSQLAlchemyRecordManagers(SQLAlchemyDatastoreTestCase, WithRecordManagers):
    pass


class TestSQLAlchemyRecordManagerWithIntegerSequences(WithSQLAlchemyRecordManagers,
                                                      IntegerSequencedItemTestCase):
    pass


class TestSQLAlchemyRecordManagerWithTimestampSequences(WithSQLAlchemyRecordManagers,
                                                        TimestampSequencedItemTestCase):
    pass


class TestSimpleIteratorWithSQLAlchemy(WithSQLAlchemyRecordManagers,
                                       SimpleSequencedItemteratorTestCase):
    pass


class TestThreadedIteratorWithSQLAlchemy(WithSQLAlchemyRecordManagers,
                                         ThreadedSequencedItemIteratorTestCase):
    use_named_temporary_file = True
