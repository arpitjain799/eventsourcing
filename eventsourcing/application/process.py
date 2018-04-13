from collections import OrderedDict, defaultdict

import six
from six import with_metaclass

from eventsourcing.application.simple import SimpleApplication
from eventsourcing.domain.model.decorators import retry
from eventsourcing.domain.model.events import publish, subscribe, unsubscribe
from eventsourcing.exceptions import CausalDependencyFailed, OperationalError, PromptFailed, RecordConflictError
from eventsourcing.infrastructure.base import RelationalRecordManager
from eventsourcing.infrastructure.eventsourcedrepository import EventSourcedRepository
from eventsourcing.infrastructure.sqlalchemy.manager import TrackingRecordManager
from eventsourcing.interface.notificationlog import NotificationLogReader
from eventsourcing.utils.transcoding import json_dumps, json_loads
from eventsourcing.utils.uuids import uuid_from_application_name


class Pipeline(object):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __or__(self, other):
        return Pipeline(self, other)

    def __iter__(self):
        for term in (self.left, self.right):
            if isinstance(term, Pipeline):
                for item in term:
                    yield item
            else:
                assert issubclass(term, Process), term
                yield term


class PipeableMetaclass(type):

    def __or__(self, other):
        return Pipeline(self, other)


class Pipeable(with_metaclass(PipeableMetaclass)):
    pass


class Process(Pipeable, SimpleApplication):
    tracking_record_manager_class = TrackingRecordManager

    def __init__(self, name=None, policy=None, setup_tables=False, setup_table=False, session=None,
                 persist_event_type=None, **kwargs):
        setup_table = setup_tables = setup_table or setup_tables
        super(Process, self).__init__(name=name, setup_table=setup_table, session=session,
                                      persist_event_type=persist_event_type, **kwargs)
        # self._cached_entities = {}
        self.policy_func = policy
        self.readers = OrderedDict()
        self.is_reader_position_ok = defaultdict(bool)

        # Setup tracking records.
        self.tracking_record_manager = self.tracking_record_manager_class(self.datastore.session)
        if setup_tables and not session:
            self.datastore.setup_table(
                self.tracking_record_manager.record_class
            )

        ## Prompts policy.
        #
        # 1. Publish prompts whenever domain events are published (important: after persisted).
        # 2. Run this process whenever upstream prompted followers to pull for new notification.
        subscribe(predicate=self.persistence_policy.is_event, handler=self.publish_prompt_from_event)
        subscribe(predicate=self.is_upstream_prompt, handler=self.run)
        # Todo: Maybe make a prompts policy object?

    def follow(self, upstream_application_name, notification_log):
        # Create a reader.
        reader = NotificationLogReader(notification_log)
        self.readers[upstream_application_name] = reader

    @retry((OperationalError, RecordConflictError), max_attempts=100, wait=0.01)
    def run(self, prompt=None):

        if prompt is None:
            readers_items = self.readers.items()
        else:
            assert isinstance(prompt, Prompt)
            reader = self.readers[prompt.process_name]
            readers_items = [(prompt.process_name, reader)]

        notification_count = 0
        for upstream_application_name, reader in readers_items:

            if not self.is_reader_position_ok[upstream_application_name]:
                self.set_reader_position_from_tracking_records(reader, upstream_application_name)
                self.is_reader_position_ok[upstream_application_name] = True

            for notification in reader.read():
                # Todo: Put this on a queue and then get the next one.
                notification_count += 1

                # Todo: Get this from a queue and do it in a different thread?
                # Domain event from notification.
                event = self.event_store.sequenced_item_mapper.from_topic_and_data(
                    topic=notification['event_type'],
                    data=notification['state']
                )

                # Wait for causal dependencies to be satisfied.
                upstream_causal_dependencies = notification.get('causal_dependencies')
                if upstream_causal_dependencies is not None:
                    upstream_causal_dependencies = json_loads(upstream_causal_dependencies)
                if upstream_causal_dependencies is None:
                    upstream_causal_dependencies = []
                for causal_dependency in upstream_causal_dependencies:
                    pipeline_id = causal_dependency['pipeline_id']
                    notification_id = causal_dependency['notification_id']

                    if not self.tracking_record_manager.has_tracking_record(
                        application_id=self.application_id,
                        upstream_application_name=upstream_application_name,
                        pipeline_id=pipeline_id,
                        notification_id=notification_id
                    ):
                        self.is_reader_position_ok[upstream_application_name] = False

                        raise CausalDependencyFailed({
                            'application_id': self.application_id,
                            'upstream_application_name': upstream_application_name,
                            'pipeline_id': pipeline_id,
                            'notification_id': notification_id
                        })

                # Call policy with the event.
                unsaved_aggregates, causal_dependencies = self.call_policy(event)
                # Todo: Also include the received event in the causal dependencies.

                # Write records.
                try:
                    event_records = self.write_records(
                        unsaved_aggregates, notification, upstream_application_name, causal_dependencies
                    )
                except Exception as e:
                    self.is_reader_position_ok[upstream_application_name] = False
                    # self._cached_entities = {}
                    raise e
                else:
                    # Publish a prompt if there are new notifications.
                    # Todo: Optionally send events as prompts, will save reading database
                    # if it arrives in correct order, but risks overloading the recipient.
                    if event_records:
                        self.publish_prompt(max([e.id for e in event_records]))

        return notification_count

    def set_reader_position_from_tracking_records(self, reader, upstream_application_name):
        max_record_id = self.tracking_record_manager.get_max_record_id(
            application_name=self.name,
            upstream_application_name=upstream_application_name,
            pipeline_id=self.pipeline_id,
        )
        reader.seek(max_record_id or 0)

    def call_policy(self, event):
        repository = RepositoryWrapper(self.repository)
        new_aggregates = self.policy(repository, event)
        repo_aggregates = list(repository.retrieved_aggregates.values())
        all_aggregates = repo_aggregates[:]
        if new_aggregates is not None:
            if not isinstance(new_aggregates, (list, tuple)):
                new_aggregates = [new_aggregates]
            all_aggregates += new_aggregates

        highest = defaultdict(int)
        for entity_id, entity_version in repository.causal_dependencies:
            pipeline_id, notification_id = self.event_store.record_manager.get_pipeline_and_notification_id(
                entity_id, entity_version
            )
            if pipeline_id != self.pipeline_id:
                highest[pipeline_id] = max(notification_id, highest[pipeline_id])

        causal_dependencies = []
        for pipeline_id, notification_id in highest.items():
            causal_dependencies.append({
                'pipeline_id': str(pipeline_id),
                'notification_id': notification_id
            })
        # Todo: Optionally reference causal dependencies in current pipeline.
        # Todo: Support processing notification from a single pipeline in parallel, according to dependencies.
        return all_aggregates, causal_dependencies

    def policy(self, repository, event):
        return self.policy_func(self, repository, event) if self.policy_func is not None else None

    def write_records(self, aggregates, notification, upstream_application_name, causal_dependencies):
        # Construct tracking record.
        tracking_record = self.construct_tracking_record(notification, upstream_application_name)

        # Construct event records.
        event_records = self.construct_event_records(aggregates, causal_dependencies)

        # Write event records with tracking record.
        record_manager = self.event_store.record_manager
        assert isinstance(record_manager, RelationalRecordManager)
        record_manager.write_records(records=event_records, tracking_record=tracking_record)
        # Todo: Maybe optimise by skipping writing lots of solo tracking records
        # (ie writes that don't have any new events). Maybe just write one at the
        # end of a run, if necessary, or only once during a period of time when
        # nothing happens.

        return event_records

    def is_upstream_prompt(self, prompt):
        return isinstance(prompt, Prompt) and prompt.process_name in self.readers.keys()

    def publish_prompt_from_event(self, _):
        # Don't have record, so just prompt without an end position.
        self.publish_prompt()

    def publish_prompt(self, end_position=None):
        if end_position is not None:
            assert isinstance(end_position, six.integer_types), end_position
        prompt = Prompt(self.name, self.pipeline_id, end_position=end_position)
        try:
            publish(prompt)
        except PromptFailed:
            raise
        except Exception as e:
            raise PromptFailed("{}: {}".format(type(e), str(e)))

    def construct_event_records(self, aggregates, causal_dependencies):
        assert isinstance(aggregates, (list, tuple))
        record_manager = self.event_store.record_manager

        event_records = []
        for aggregate in aggregates:
            pending_events = aggregate.__batch_pending_events__()
            sequenced_items = self.event_store.to_sequenced_item(pending_events)
            assert isinstance(record_manager, RelationalRecordManager)
            event_records += record_manager.to_records(sequenced_items)

        current_max = record_manager.get_max_record_id() or 0
        for event_record in event_records:
            current_max += 1
            event_record.id = current_max

        causal_dependencies = json_dumps(causal_dependencies)

        if hasattr(record_manager.record_class, 'causal_dependencies'):
            for event_record in event_records:
                event_record.causal_dependencies = causal_dependencies

        return event_records

    def construct_tracking_record(self, notification, upstream_application_name):
        upstream_application_id = uuid_from_application_name(upstream_application_name)
        kwargs = {
            'application_id': self.application_id,
            'upstream_application_id': upstream_application_id,
            'pipeline_id': self.pipeline_id,
            'notification_id': notification['id'],
            'originator_id': notification['originator_id'],
            'originator_version': notification['originator_version']
        }
        return self.tracking_record_manager.record_class(**kwargs)

    def close(self):
        unsubscribe(predicate=self.is_upstream_prompt, handler=self.run)
        unsubscribe(predicate=self.persistence_policy.is_event, handler=self.publish_prompt_from_event)
        super(Process, self).close()


class RepositoryWrapper(object):
    def __init__(self, repository):
        self.retrieved_aggregates = {}
        assert isinstance(repository, EventSourcedRepository)
        self.repository = repository
        self.causal_dependencies = []

    def __getitem__(self, entity_id):
        try:
            return self.retrieved_aggregates[entity_id]
        except KeyError:
            entity = self.repository.__getitem__(entity_id)
            self.retrieved_aggregates[entity_id] = entity
            self.causal_dependencies.append((entity.id, entity.__version__))
            return entity

    def __contains__(self, entity_id):
        return self.repository.__contains__(entity_id)


class Prompt(object):
    def __init__(self, process_name, pipeline_id, end_position=None):
        self.process_name = process_name
        self.pipeline_id = pipeline_id
        self.end_position = end_position


class System(object):
    def __init__(self, *pipelines):
        """
        Initialises a "process network" system object.

        :param pipelines: Pipelines of process classes.

        Each pipeline of process classes shows directly which process
        follows which other process in the system.

        For example, the pipeline (A | B | C) shows that B follows A,
        and C follows B.

        The pipeline (A | A) shows that A follows A.

        The pipeline (A | B | A) shows that B follows A, and A follows B.

        The pipelines ((A | B | A), (A | C | A)) is equivalent to (A | B | A | C | A).
        """
        self.pipelines = pipelines
        self.process_classes = set([c for l in self.pipelines for c in l])
        self.processes_by_name = None
        self.is_session_shared = True

        # Determine which process follows which.
        self.followings = OrderedDict()
        for pipeline in self.pipelines:
            previous = None
            for process_class in pipeline:
                assert issubclass(process_class, Process), process_class
                if previous is not None:
                    # Follower follows the followed.
                    follower = process_class
                    followed = previous
                    try:
                        follows = self.followings[follower]
                    except KeyError:
                        follows = []
                        self.followings[follower] = follows

                    if followed not in follows:
                        follows.append(followed)

                previous = process_class

    # Todo: Extract function to new 'SinglethreadRunner' class or something (like the 'Multiprocess' class)?
    def setup(self):
        assert self.processes_by_name is None, "Already running"
        self.processes_by_name = {}

        # Construct the processes.
        session = None
        for process_class in self.process_classes:
            process = process_class(session=session, setup_tables=bool(session is None))
            self.processes_by_name[process.name] = process
            if self.is_session_shared:
                if session is None:
                    session = process.session

        # Configure which process follows which.
        for follower_class, follows in self.followings.items():
            follower = self.processes_by_name[follower_class.__name__.lower()]
            for followed_class in follows:
                followed = self.processes_by_name[followed_class.__name__.lower()]
                follower.follow(followed.name, followed.notification_log)

    def __getattr__(self, process_name):
        assert self.processes_by_name is not None, "Not running"
        return self.processes_by_name[process_name]

    def close(self):
        assert self.processes_by_name is not None, "Not running"
        for process in self.processes_by_name.values():
            process.close()
        self.processes_by_name = None

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
