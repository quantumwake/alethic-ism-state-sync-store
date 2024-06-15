import asyncio
import json
import os
import signal
import sys
from typing import Optional

import dotenv
import pulsar
from core.base_message_router import Router
from core.processor_state import State
from core.pulsar_message_producer_provider import PulsarMessagingProducerProvider
from db.processor_state_db_storage import PostgresDatabaseStorage
from pydantic import ValidationError

from basic_cache import memoize
from logger import logging

dotenv.load_dotenv()
logging.info('starting up pulsar consumer for state sync store')

# pulsar/kafka related
MSG_URL = os.environ.get("MSG__URL", "pulsar://localhost:6650")
MSG_TOPIC = os.environ.get("MSG_TOPIC", "ism_state_sync_store")
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

router_provider = PulsarMessagingProducerProvider()

# publish router
message_router = Router(
    provider=router_provider,
    yaml_file=ROUTING_FILE
)

# consumer config
client = pulsar.Client(MSG_URL)
consumer = client.subscribe(MSG_TOPIC, MSG_TOPIC_SUBSCRIPTION)

storage = PostgresDatabaseStorage(
    database_url=DATABASE_URL,
    incremental=True
)


#
# # @memoize
async def fetch_state(state_id: str) -> Optional[State]:
    state = storage.load_state(state_id=state_id)
    return state


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

async def apply_query_state_entry(state: State, query_state_entry: dict):
    # fetch data to be persisted

    if not state:
        raise ValidationError(f'invalid state')

    # # apply state information to the state store
    # state.apply


async def execute_query_state_entry(state: State, message: dict):
    if 'query_state_entry' not in message:
        raise ValidationError(f'unable to extract query state entry from consumed message')

    query_state_entry = message['query_state_entry']
    state.apply_query_state(query_state=query_state_entry)
    logging.info(f'persisting state: {state.id} to storage {state.config.storage_class} with count: {state.count}')
    state = storage.save_state(state=state)


async def execute_query_state_list(state: State, message: dict):
    if 'query_state_list' not in message:
        raise ValidationError(f'unable to extract query state entry from consumed message')

    query_state_list = message['query_state_list']

    processor = storage.fetch_processor(message['processor_id'])
    provider = storage.fetch_processor_provider(message['provider_id'])

    for query_state_entry in query_state_list:
        state.apply_query_state(
            query_state=query_state_entry,
            scope_variable_mappings={
                "provider": provider,
                "processor": processor
            }
        )

    logging.info(f'persisting state: {state.id} to storage {state.config.storage_class} with count: {state.count}')
    state = storage.save_state(
        state=state)  # create any new columns and save all the data # TODO definitely needs some caching/incremental updates
    state = storage.update_state_count(
        state=state)  # we explicitly update the state count TODO need to figure this out with cache


async def execute(message_dict: dict):
    if 'state_id' not in message_dict:
        raise ValidationError(f'unable to identity state id from consumed message')

    if 'type' not in message_dict:
        raise ValidationError(f'unable to identify state type, must be query_state_list or query_state_entry')

    message_type = message_dict['type']
    state_id = message_dict['state_id']

    # fetch the state object from the cache or backend
    state = await fetch_state(state_id=state_id)

    if message_type == 'query_state_list':
        return await execute_query_state_list(state=state, message=message_dict)
    elif message_type == 'query_state_entry':
        return await execute_query_state_entry(state=state, message=message_dict)

    raise NotImplementedError(f'unsupported query state message type {message_type}')


async def qa_topic_consumer():
    while RUNNING:
        msg = None
        data = None
        try:
            msg = consumer.receive()
            data = msg.data().decode("utf-8")
            logging.info(f'Message received with {data}')
            message_dict = json.loads(data)
            state = await execute(message_dict)

            # send ack that the message was consumed.
            consumer.acknowledge(msg)
        except pulsar.Interrupted:
            logging.error("Stop receiving messages")
            break
        except ValidationError as e:
            # it is safe to assume that if we get a validation error, there is a problem with the json object
            consumer.acknowledge(msg)
            logging.error(f"Message validation error: {e}, data: {data}")
        except Exception as e:
            consumer.acknowledge(msg)
            logging.error(f"An error occurred: {e}, data: {data}")


def graceful_shutdown(signum, frame):
    global RUNNING
    print("Received SIGTERM signal. Gracefully shutting down.")
    RUNNING = False
    sys.exit(0)


# Attach the SIGTERM signal handler
signal.signal(signal.SIGTERM, graceful_shutdown)

if __name__ == '__main__':
    asyncio.run(qa_topic_consumer())
