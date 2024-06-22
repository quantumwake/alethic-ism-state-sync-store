import os
from typing import Optional

import dotenv
import pulsar
from core.base_message_provider import BaseMessagingConsumer
from core.base_message_router import Router
from core.base_model import ProcessorState, ProcessorStatusCode
from core.processor_state import State
from core.pulsar_message_producer_provider import PulsarMessagingProducerProvider
from core.pulsar_messaging_provider import PulsarMessagingConsumerProvider
from db.processor_state_db_storage import PostgresDatabaseStorage
from pydantic import ValidationError

from logger import logging

dotenv.load_dotenv()
logging.info('starting up pulsar consumer for state sync store')

# pulsar/kafka related
MSG_URL = os.environ.get("MSG_URL", "pulsar://localhost:6650")
MSG_TOPIC = os.environ.get("MSG_TOPIC", "ism_state_sync_store")
MSG_MANAGE_TOPIC = os.environ.get("MSG_MANAGE_TOPIC", "ism_state_sync_store_manage")
MSG_TOPIC_SUBSCRIPTION = os.environ.get("MSG_TOPIC_SUBSCRIPTION", "ism_state_sync_store_subscription")

# database related
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres1@localhost:5432/postgres")

# Message Routing File (
#   The responsibility of this state sync store is to take inputs and
#   store them into a consistent state storage class. After, the intent is
#   to automatically route the newly synced data to the next state processing unit
#   route them to the appropriate destination, as defined by the
#   route selector
# )
ROUTING_FILE = os.environ.get("ROUTING_FILE", '.routing.yaml')
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# flag that determines whether to shut down the consumers
RUNNING = True

# the routing of messages (successful pre/intra/post events, or failed events)
router_provider = PulsarMessagingProducerProvider()
message_router = Router(
    provider=router_provider,
    yaml_file=ROUTING_FILE
)

# catch-all storage class configuration
storage = PostgresDatabaseStorage(
    database_url=DATABASE_URL,
    incremental=True
)

# pulsar messaging provider is used, the routes are defined in the routing.yaml
pulsar_provider = PulsarMessagingProducerProvider()
router = Router(
    provider=pulsar_provider,
    yaml_file=ROUTING_FILE
)

# find the monitor route for telemetry updates
monitor_route = router.find_router("processor/monitor")

# define the consumer subsystem to use, in this case we are using pulsar but we can also use kafka
messaging_provider = PulsarMessagingConsumerProvider(
    message_url=MSG_URL,
    message_topic=MSG_TOPIC,
    message_topic_subscription=MSG_TOPIC_SUBSCRIPTION,
    management_topic=MSG_MANAGE_TOPIC
)


# # @memoize
async def fetch_state(state_id: str) -> Optional[State]:
    state = storage.load_state(state_id=state_id)
    return state
#

# setup the state data synchronization consumer class
class MessagingStateSyncConsumer(BaseMessagingConsumer):

    async def pre_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    async def post_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    async def execute(self, message: dict):
        if 'type' not in message:
            raise ValueError(f'unable to identify state type, must be query_state_list or query_state_entry')
        message_type = message['type']

        if 'route_id' not in message:
            raise ValueError(f'unable to identity state id from consumed message')
        route_id = message['route_id']

        # fetch processor state route information in order to know where we are persisting the data
        processor_state = storage.fetch_processor_state_route(route_id=route_id)

        # ensure that processor state route is correct
        if not processor_state or len(processor_state) != 1:
            raise ValueError(
                f'unable to identity route id {route_id}, '
                f'expected 1 result, received {processor_state}'
            )
        processor_state = processor_state[0]

        # fetch the state object from the cache or backend
        state = await fetch_state(state_id=processor_state.state_id)

        if message_type != 'query_state_list':
            raise ValueError(f'invalid message type {message_type}')

        # persist the query state list
        return await self.apply_query_state(
            state=state,
            processor_state_route=processor_state,
            message=message
        )

    async def apply_query_state(self, state: State, processor_state_route: ProcessorState, message: dict):
        if 'query_state_list' not in message:
            raise ValidationError(f'unable to extract query state entry from consumed message')

        query_state_list = message['query_state_list']
        processor = storage.fetch_processor(processor_id=processor_state_route.processor_id)
        provider = storage.fetch_processor_provider(id=processor.provider_id)

        for query_state_entry in query_state_list:
            state.apply_query_state(
                query_state=query_state_entry,
                scope_variable_mappings={
                    "provider": provider,
                    "processor": processor
                }
            )

        logging.info(f'persisting state: {state.id} to storage {state.config.storage_class} with count: {state.count}')

        # create any new columns and save all the data # TODO definitely needs some caching/incremental updates
        state = storage.save_state(state=state)

        # we explicitly update the state count TODO need to figure this out with cache
        state = storage.update_state_count(state=state)

        return state


if __name__ == '__main__':
    monitor_route = router.find_router('processor/monitor')

    consumer = MessagingStateSyncConsumer(
        name="MessagingStateSyncConsumer",
        storage=storage,
        messaging_provider=messaging_provider,
        monitor_route=monitor_route
    )

    consumer.setup_shutdown_signal()
    consumer.start_topic_consumer()



# def apply_query_state(state: State, query_state: dict):
#
#     # pre-state apply - any transformation and column before applying the state
#     query_state = self.pre_state_apply(query_state=query_state)
#
#     # apply the response query state to the output state
#     self.output_state.apply_columns(query_state=query_state)
#     self.output_state.apply_row_data(query_state=query_state)
#
#     # post-state apply - the completed function
#     return self.post_state_apply(query_state=query_state)
#
# async def apply_query_state_entry(state: State, query_state_entry: dict):
#     # fetch data to be persisted
#
#     if not state:
#         raise ValidationError(f'invalid state')
#
#     # # apply state information to the state store
#     # state.apply


#
# async def qa_topic_consumer():
#     while RUNNING:
#         msg = None
#         data = None
#         try:
#             msg = consumer.receive()
#             data = msg.data().decode("utf-8")
#             logging.info(f'Message received with {data}')
#             message_dict = json.loads(data)
#             state = await execute(message_dict)
#
#             # send ack that the message was consumed.
#             consumer.acknowledge(msg)
#         except pulsar.Interrupted:
#             logging.error("Stop receiving messages")
#             break
#         except ValidationError as e:
#             # it is safe to assume that if we get a validation error, there is a problem with the json object
#             consumer.acknowledge(msg)
#             logging.error(f"Message validation error: {e}, data: {data}")
#         except Exception as e:
#             consumer.acknowledge(msg)
#             logging.error(f"An error occurred: {e}, data: {data}")

#
# def graceful_shutdown(signum, frame):
#     global RUNNING
#     print("Received SIGTERM signal. Gracefully shutting down.")
#     RUNNING = False
#     sys.exit(0)
#
#
# # Attach the SIGTERM signal handler
# signal.signal(signal.SIGTERM, graceful_shutdown)
#
# if __name__ == '__main__':
#     asyncio.run(qa_topic_consumer())
