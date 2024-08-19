#!/bin/bash

# This script runs dev ntrip docker container

# Build the Docker image
docker build \
    -t av_ntrip_client:latest-dev \
    -f Dockerfile --target dev .

# Run the Docker container and pass any provided arguments
docker run -it --rm --net host --privileged \
    -v /etc/localtime:/etc/localtime:ro \
    -v ./scripts:/workspace/scripts \
    av_ntrip_client:latest-dev
