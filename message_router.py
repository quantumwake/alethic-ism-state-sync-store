# pulsar messaging provider is used, the routes are defined in the routing.yaml
import os

from core.messaging.base_message_router import Router
from core.messaging.nats_message_provider import NATSMessageProvider

ROUTING_FILE = os.environ.get("ROUTING_FILE", '.routing.yaml')

message_provider = NATSMessageProvider()
message_router = Router(
    provider=message_provider,
    yaml_file=ROUTING_FILE
)

# find the monitor route for telemetry updates
monitor_route = message_router.find_route("processor/monitor")

# find the state sync route
state_sync_route = message_router.find_route("processor/state/sync")

# find the state router route
state_router_route = message_router.find_route("processor/state/router")
