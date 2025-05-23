import os
import dotenv
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
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Message Routing File (
#   The responsibility of this state sync store is to take inputs and
#   store them into a consistent state storage class. After, the intent is
#   to automatically route the newly synced data to the next state processing unit
#   route them to the appropriate destination, as defined by the
#   route selector
# )
ROUTING_FILE = os.environ.get("ROUTING_FILE", '.routing.yaml')

