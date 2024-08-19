#!/bin/bash

# This scripts runs runtime ntrip docker container and
#  passes any arguments to the ntrip_client app

# Build the Docker image
docker build \
    -t av_ntrip_client:latest \
    -f Dockerfile --target runtime .

# Run the Docker container and pass any provided arguments
docker run -it --rm --net host --privileged \
    -v /etc/localtime:/etc/localtime:ro \
    av_ntrip_client:latest "$@"
