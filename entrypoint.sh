#!/bin/bash

# Initialize Conda
. /opt/conda/etc/profile.d/conda.sh

# Activate the Conda environment
conda activate alethic-ism-state-sync-store

# Execute the command provided to the docker run command
exec "$@"

