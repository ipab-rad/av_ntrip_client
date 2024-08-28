#!/bin/bash
# ---------------------------------------------------------------------------
# Build Docker image, then run Ntrip Client (runtime or interactive bash)
# ---------------------------------------------------------------------------


# Function to print usage
usage() {
    echo "
Usage: dev.sh [-b|bash] [--param-file] [--use-fix-location] [--debug ] [-h|--help]

Where:
    -b | bash           Open bash in docker container
    --param-file        Path to the YAML file containing Ntrip server credentials
    --use-fix-location  Use fixed location for Ntrip requests
    --debug             Run Ntrip Client in debug mode
    -h | --help         Show this help message
    "d
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
        --use-fix-location|--debug|--param-file)
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

# Create logs dir
mkdir -p scripts/logs

# Build the Docker image
docker build \
    -t av_ntrip_client:latest \
    -f Dockerfile --target runtime .

# Run the Docker container and pass any provided arguments
docker run -it --rm --net host --privileged \
    -v /etc/localtime:/etc/localtime:ro \
    -v ./scripts/logs:/workspace/scripts/logs \
    $ENTRYPOINT \
    av_ntrip_client:latest $BASH_CMD
