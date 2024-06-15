# Alethic Instruction-Based State Machine (State Store Synchronizer)

This processor module is designed to respond to events from Pulsar and can be extended to other pub/sub systems like Kafka.

## Setup and Configuration
If you are using miniconda, something along the lines of:
- Add Conda channel: `conda config --add channels ~/miniconda3/envs/local_channel`.
- Show Conda channels: `conda config --show channels`.

## Environment Initialization
- Create environment: `conda env create -f environment.yaml`.
- Activate environment: `conda activate alethic-ism-state-sync-store`.

## Installation (Manually- might need additional libs, this document is outdated)
Install necessary packages including Pulsar client, Pydantic, Python-dotenv, and others:
- `conda install pulsar-client`
- `conda install annotated-types`
- `conda install pydantic` (Check compatibility on Apple Silicon)
- `conda install python-dotenv`
- `conda install tenacity`
- `conda install pyyaml`
- `conda install psycopg2`

## Troubleshooting
- nothing here yet

## Alethic Dependencies
- Remote: `conda install alethic-ism-core`, `conda install alethic-ism-db`.
- Local: Install from the local channel if remote versions aren't available.

## Testing
- ** testing is not exactly working right now **
- Install pytest: `conda install pytest`.

## Contribution
Contributions, questions, and feedback are highly encouraged. Contact us for any queries or suggestions.

For more updates and involvement opportunities, visit the [Alethic ISM GitHub page](https://github.com/quantumwake/alethic) or create an issue/comment ticket.
