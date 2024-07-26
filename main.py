import asyncio
import json
from typing import Optional, Dict, List

from core.base_model import ProcessorStateDirection
from core.messaging.base_message_provider import BaseMessageConsumer
from core.messaging.base_message_route_model import BaseRoute
from core.messaging.nats_message_provider import NATSMessageProvider
from core.monitored_processor_state import MonitoredProcessorState
from core.processor_state import State
from db.processor_state_db_storage import PostgresDatabaseStorage

from environment import DATABASE_URL, MSG_URL, MSG_TOPIC, MSG_TOPIC_SUBSCRIPTION, MSG_MANAGE_TOPIC
from logger import logging
from message_router import monitor_route, state_sync_route, state_router_route

# flag that determines whether to shut down the consumers
RUNNING = True

# catch-all storage class configuration
storage = PostgresDatabaseStorage(
    database_url=DATABASE_URL,
    incremental=True
)

# define the consumer subsystem to use, in this case we are using pulsar but we can also use kafka
message_provider = NATSMessageProvider()


# setup the state data synchronization consumer class
class MessagingStateSyncConsumer(BaseMessageConsumer, MonitoredProcessorState):

    def __init__(self, route: BaseRoute, monitor_route: BaseRoute = None, **kwargs):
        BaseMessageConsumer.__init__(self, route)
        MonitoredProcessorState.__init__(self, monitor_route, **kwargs)

    async def pre_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    async def post_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    # # @memoize
    async def fetch_state(self, state_id: str) -> Optional[State]:
        state = storage.load_state(state_id=state_id)
        return state

    async def execute(self, message: dict):
        if 'type' not in message:
            raise ValueError(f'unable to identify state type, must be one of: '
                             f'[query_state_route, query_state_direct')

        message_type = message['type']
        if message_type == 'query_state_direct':
            query_states, state = await self.execute_direct(message=message)
        elif message_type == 'query_state_route':
            query_states, state = await self.execute_route(message=message)
        else:
            raise ValueError(f'invalid message type {message_type}')

        return await self.route_query_states(state=state, query_states=query_states)

    async def execute_direct(self, message: dict):

        if 'state_id' not in message:
            raise ValueError(f'no state information defined in message: {message}')
        state_id = message['state_id']

        # fetch the state object from the cache or backend
        state = await self.fetch_state(state_id=state_id)

        # persist the query state list
        query_states = message['query_states']
        state = await self.save_state(state=state, query_states=query_states, scope_variable_mapping={
            "state_id": state_id
        })

        return query_states, state

    async def execute_route(self, message: dict):

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
        state = await self.fetch_state(state_id=processor_state.state_id)
        query_states = message['query_states']
        processor = storage.fetch_processor(processor_id=processor_state.processor_id)
        provider = storage.fetch_processor_provider(id=processor.provider_id)

        state = await self.save_state(state=state, query_states=query_states, scope_variable_mapping={
            "route_id": route_id,
            "provider": provider,
            "processor": processor,
            "processor_state": processor_state
        })

        return query_states, state

    async def save_state(self, state: State, query_states: [], scope_variable_mapping: dict = {}):
        for query_state_entry in query_states:
            state.apply_query_state(
                query_state=query_state_entry,
                scope_variable_mappings=scope_variable_mapping
            )

        logging.info(f'persisting state: {state.id} to storage {state.config.storage_class} with count: {state.count}')

        # create any new columns and save all the data # TODO definitely needs some caching/incremental updates
        state = storage.save_state(state=state)

        # we explicitly update the state count TODO need to figure this out with cache
        state = storage.update_state_count(state=state)

        return state

    async def route_query_states(self, state: State, query_states: List[Dict]):

        state_id = state.id
        if not state.config.flag_auto_route_output_state:
            logging.debug(f'flag auto route query states forward is disabled, for state id {state_id}')
            return

        # the current state id is an INPUT into other processors (if any)
        forward_routes = storage.fetch_processor_state_route(
            state_id=state_id,
            direction=ProcessorStateDirection.INPUT
        )

        # ensure there are forwarding hop(s)
        if not forward_routes:
            logging.debug(f'no forward routes found for state id: {state_id}')
            return

        # iterate and send query states to next hops
        [state_router_route.send_message(json.dumps({
            "route_id": forward_route.id,
            "type": "query_state_route",
            "input_state_id": state_id,
            "query_state": query_states}
        )) for forward_route in forward_routes]


if __name__ == '__main__':
    consumer = MessagingStateSyncConsumer(
        route=state_sync_route,
        monitor_route=monitor_route
    )

    consumer.setup_shutdown_signal()
    asyncio.get_event_loop().run_until_complete(consumer.start_consumer())
