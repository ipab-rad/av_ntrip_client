#!/bin/bash
# ---------------------------------------------------------------------------
# Build Docker image, then run Ntrip Client (runtime or interactive bash)
# ---------------------------------------------------------------------------


# Function to print usage
usage() {
    echo "
Usage: dev.sh [-b|bash] [--use-fix-location] [--debug ] [-h|--help]

Where:
    -b | bash           Open bash in docker container
    --use-fix-location  Use fixed location for Ntrip Client
    --debug             Run Ntrip Client in debug mode
    -h | --help         Show this help message
    "
    exit 1
}

ENTRYPOINT=""
BASH_CMD="$@"

# Parse command-line options
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -b|bash)
            ENTRYPOINT="--entrypoint /bin/bash"
            BASH_CMD=""
            ;;
        --use-fix-location|--debug)
            # These flags are intended to be passed to
            # the Docker container, so no action is needed here
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
    -t av_ntrip_client:latest \
    -f Dockerfile --target runtime .

# Run the Docker container and pass any provided arguments
docker run -it --rm --net host --privileged \
    -v /etc/localtime:/etc/localtime:ro \
    $ENTRYPOINT \
    av_ntrip_client:latest $BASH_CMD
