#!/bin/bash
# ----------------------------------------------------------------
# Build docker dev stage and add local code for live development
# ----------------------------------------------------------------

BASH_CMD=""

# Function to print usage
usage() {
    echo "
Usage: dev.sh [-b|bash] [-h|--help]

Where:
    -b | bash       Open bash in docker container
    -h | --help     Show this help message
    "
    exit 1
}

# Parse command-line options
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -b|bash)
            BASH_CMD=bash
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
    shift
done


# Build the Docker image
docker build \
    -t av_ntrip_client:latest-dev \
    -f Dockerfile --target dev .

# Run the Docker container and pass any provided arguments
docker run -it --rm --net host --privileged \
    -v /etc/localtime:/etc/localtime:ro \
    -v ./scripts:/workspace/scripts \
    av_ntrip_client:latest-dev $BASH_CMD
