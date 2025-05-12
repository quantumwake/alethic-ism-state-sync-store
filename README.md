# Alethic Instruction-Based State Machine (State Sync Store)

The State Sync Store is a component of the Alethic Instruction-Based State Machine (ISM) framework. It provides centralized state synchronization and persistence for the ISM processing pipeline, with automatic routing capabilities to forward state updates to downstream processors.

## Overview

The State Sync Store:
- Receives and processes state updates from various components of the ISM framework
- Stores these state changes persistently in a PostgreSQL database
- Automatically routes updated state information to dependent processors
- Provides caching mechanisms to improve performance
- Handles both direct state access and route-based state processing

## Architecture

The system uses a message-based architecture with NATS as the messaging provider. It consumes state update messages, processes them through the `MessagingStateSyncConsumer` class, and persists changes to the database. It can then optionally route updated state information to downstream processors based on configuration.

## Requirements

- Python 3.10 or higher
- PostgreSQL database
- NATS messaging system
- uv package management tool: `pip install uv`

## Setup and Configuration

### Environment Variables

The application is configured using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| MSG_URL | NATS server URL | pulsar://localhost:6650 |
| MSG_TOPIC | Main message topic | ism_state_sync_store |
| MSG_MANAGE_TOPIC | Management message topic | ism_state_sync_store_manage |
| MSG_TOPIC_SUBSCRIPTION | Topic subscription name | ism_state_sync_store_subscription |
| DATABASE_URL | PostgreSQL connection string | postgresql://postgres:postgres1@localhost:5432/postgres |
| LOG_LEVEL | Logging level | INFO |
| ROUTING_FILE | Path to YAML routing configuration | .routing.yaml |

### Installation

1. Install dependencies:
   ```
   uv pip install -r requirements.txt
   ```

2. Configure your environment variables or create a `.env` file

3. Ensure your PostgreSQL database is accessible

4. Create a `.routing.yaml` file for message routing configuration

## Docker Build and Deployment

### Docker

- Build the Docker container:
  ```
  make build
  ```

- Run the Docker container:
  ```
  make run
  ```

### Kubernetes

A Kubernetes deployment configuration is available in the `k8s` directory:

- The deployment requires secrets for database configuration and routing
- Mount points for the routing configuration are provided
- The deployment is configured for the 'alethic' namespace

## Testing

- Run tests:
  ```
  make test
  ```

## Message Types

The store handles several message types:

- `query_state_direct`: Direct state access via state ID
- `query_state_route`: Route-based state access
- `query_state_entry`: Internal routing message for forwarding state updates

## Performance Considerations

The codebase includes several TODOs related to performance improvements:
- State persistence is a potential bottleneck
- Caching is implemented with time-based invalidation (configurable)
- Batch processing of state updates is planned for future implementation
- Consideration for distributed state storage to improve scalability

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the LICENSE file for details.