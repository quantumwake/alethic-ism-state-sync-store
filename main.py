import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, List

from core.base_model import ProcessorStateDirection, Processor, ProcessorProvider, ProcessorState
from core.messaging.base_message_provider import BaseMessageConsumer
from core.messaging.base_message_route_model import BaseRoute
from core.messaging.nats_message_provider import NATSMessageProvider
from core.processor_state import State
from db.processor_state_db_storage import PostgresDatabaseStorage

from environment import DATABASE_URL, MSG_URL, MSG_TOPIC, MSG_TOPIC_SUBSCRIPTION, MSG_MANAGE_TOPIC
from logger import logging
from message_router import monitor_route, state_sync_route, state_router_route

# flag that determines whether to shut down the consumers
RUNNING = True
# r = redis.Redis(host='localhost', port=6379, db=0)

# catch-all storage class configuration
storage = PostgresDatabaseStorage(
    database_url=DATABASE_URL,
    incremental=True
)

# define the consumer subsystem to use, in this case we are using pulsar but we can also use kafka
message_provider = NATSMessageProvider()


class StateCacheItem:

    def __init__(self,
                 state: State,
                 processor: Processor,
                 provider: ProcessorProvider,
                 processor_state: ProcessorState):

        self.state: State = state
        self.processor: Processor = processor
        self.provider: ProcessorProvider = provider
        self.processor_state: ProcessorState = processor_state
        self.last_update = datetime.utcnow()


# setup the state data synchronization consumer class
class MessagingStateSyncConsumer(BaseMessageConsumer):

    def __init__(self, route: BaseRoute, monitor_route: BaseRoute = None, **kwargs):
        super().__init__(route=route, monitor_route=monitor_route)
        # self.state_cache: Dict[str, StateCacheItem] = {}
        self.route_state_cache: Dict[str, StateCacheItem] = {}

    async def pre_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    async def post_execute(self, consumer_message_mapping: dict, **kwargs):
        pass    # do not send any data synchronization updates, for now

    # # @memoize
    async def fetch_state2(self, state_id: str) -> Optional[State]:

        state = None    # start with state is not cached yet

        if state_id in self.state_cache:    # if the state is already cached
            state_cache_item = self.state_cache[state_id]   # fetch the cached item

            # calculate the time since last updating the cache element
            elapsed_last_access = datetime.utcnow() - state_cache_item.last_update
            if elapsed_last_access.seconds < 30:     # if not 30 seconds has elapsed, then use the cache item
                state = state_cache_item.state
                state_cache_item.last_update = datetime.utcnow()    # update the cache state

        # otherwise the state is null and we need to reload it and cache it again
        if not state:
            state = storage.load_state(state_id=state_id)
            self.state_cache[state_id] = StateCacheItem(state)

        # return the final state cached or just renewed/loaded
        return state

    def remove_complex_values(self, query_state):
        if not query_state:
            return query_state

        def pop(e):
            history = e['__history__'] if '__history__' in e else None
            if history:
                e.pop('__history__')

        if isinstance(query_state, list):
            for entry in query_state:
                pop(e=entry)
        else:
            pop(e=query_state)

        return query_state

    async def execute(self, message: dict):
        if 'type' not in message:
            raise ValueError(f'unable to identify state type, must be one of: '
                             f'[query_state_route, query_state_direct')

        query_state = message['query_state'] if 'query_state' in message else None

        if not query_state:
            raise ValueError(f'no query state information found in message: {message}')

        # update the query state information
        # message['query_state'] = self.remove_complex_values(query_state=query_state)
        # message['input_query_state'] = self.remove_complex_values(query_state=message['input_query_state'])

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
        # state = await self.fetch_state(state_id=state_id)
        # TODO temporary fix until we get this state synchronizer shit sorted out
        # TODO definitely do not want to be doing this outside the other path of persistence (but since the other path uses the route id and not the state id, well you get the point.....)
        state = storage.load_state(state_id=state_id, load_data=True)

        # persist the query state list
        query_states = message['query_state']
        query_states, state = await self.save_state(state=state, query_states=query_states, scope_variable_mapping={
            "state_id": state_id
        })

        return query_states, state

    async def execute_route(self, message: dict):

        if 'route_id' not in message:
            raise ValueError(f'unable to identity state id from consumed message')
        route_id = message['route_id']

        # TODO this is a total hack, the better approach would be to allow each state to have its own datastore which can be done, thus removing the burden of states being centralized
        # TODO furthermore, the state should be able to be persisted in a distributed manner, such that the state can be persisted in a distributed manner, thus removing the bottleneck of the state being centralized
        # TODO final the state should probably not use a complex data structure but be as simple as dumping a json row (aka finalized query state rather than persisting each column and value per row, although this is kind of like a key which we can use a distributed hash for I suppose? but not as efficient as I would expect)
        # TODO to say the least, this whole fucking thing around `synchronizing` state persistence needs to be looked at BADLY and quickly, as it won't scale

        load = True
        # lets check the cache first
        if route_id in self.route_state_cache:
            cache_item = self.route_state_cache[route_id]

            # calculate the time since last updating the cache element
            elapsed_last_access = datetime.utcnow() - cache_item.last_update
            if elapsed_last_access.total_seconds() >= 10:  # if not 30 seconds has elapsed, then use the cache item
                self.route_state_cache.pop(route_id)
                cache_item = None
            else:
                load = False

        if load:
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
            state = storage.load_state(state_id=processor_state.state_id, load_data=True)

            processor = storage.fetch_processor(processor_id=processor_state.processor_id)
            provider = storage.fetch_processor_provider(id=processor.provider_id)

            # TODO what happens if the routes change we need a way to invalid this, but it won't matter if we refactor and remove the state sync store altogether and replace it with decentralized persitence instead.
            cache_item = StateCacheItem(
                state=state,
                processor=processor,
                provider=provider,
                processor_state=processor_state
            )

            self.route_state_cache[route_id] = cache_item

        # persist the query state list
        query_states = message['query_state']    # likely individual state entries (a list)

        # TODO BATCH THE SHIT OUT OF THIS
        query_states, state = await self.save_state(
            state=cache_item.state,
            query_states=query_states,
            scope_variable_mapping={
                "route_id": route_id,
                "provider": cache_item.provider,
                "processor": cache_item.processor,
                "processor_state": cache_item.processor_state
            }
        )
        cache_item.state = state

        return query_states, state

    async def save_state(self, state: State, query_states: [], scope_variable_mapping: dict = {}):
        for query_state_entry in query_states:
            query_states = state.apply_query_state(
                query_state=query_state_entry,
                scope_variable_mappings=scope_variable_mapping
            )

        logging.info(f'persisting state: {state.id} to storage {state.config.storage_class} with count: {state.count}')

        # create any new columns and save all the data # TODO definitely needs some caching/incremental updates
        state = storage.save_state(state=state)

        # we explicitly update the state count TODO need to figure this out with cache
        state = storage.update_state_count(state=state)

        return query_states, state


    async def route_query_states(self, state: State, query_states: List[Dict]):

        # TODO this code apparently routes data to the next hop, however, this logic is also happening using the
        #  State Propagation Provider; in the processor directly. It might be required to have either a separate
        #  router or simple send it to the state router and let the state router make the deicision as to whether
        #  forward route this message. Although it does kind of make sense in the state sync, though the routing
        #  and data persistence should not be dependant. ARGGGG.. I think fine in the processing consumer, such that
        #  it can be the point where it can go further or not.

        # TODO already split this out to a different flag >> above comment might not be relevant.

        state_id = state.id
        if not state.config.flag_auto_route_output_state_after_save:
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
        [await state_router_route.publish(json.dumps(
            {
                "type": "query_state_entry",
                "route_id": forward_route.id,
                "query_state": query_states
            }
        )) for forward_route in forward_routes]


if __name__ == '__main__':
    consumer = MessagingStateSyncConsumer(
        route=state_sync_route,
        monitor_route=monitor_route
    )

    # TODO the bottleneck is going to be the state persistence, we need a mechanism to distribute the
    #  persistence of each state in complete consumer isolation or build the state storage machine implementation
    #  such that it can handle asynchronous persistence to the same state.

    consumer.setup_shutdown_signal()
    asyncio.get_event_loop().run_until_complete(consumer.start_consumer(consumer_no=1))
