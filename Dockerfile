# Use the official Ubuntu 24.04 as a base image
FROM ubuntu:24.04 AS base

# Set environment variables to avoid interaction during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python3, venv and pip
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* "$HOME"/.cache

# Install required Python packages using venv + pip
RUN python3 -m venv /opt/ntrip_venv \
    && /opt/ntrip_venv/bin/pip install --no-cache-dir pyyaml colorlog pyrtcm

# Set the environment variable so that the following commands use the venv
ENV PATH="/opt/ntrip_venv/bin:$PATH"

# Create a working directory
WORKDIR /workspace/scripts

FROM base AS dev

# Install dev tools
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
    net-tools \
    nano \
    python-is-python3 \
    && rm -rf /var/lib/apt/lists/* "$HOME"/.cache

# Run bash terminal by default
CMD ["bash"]

FROM base AS runtime

# Copy scripts dierectory
COPY ./scripts /workspace/scripts

# Make sure the script is executable
RUN chmod +x /workspace/scripts/ntrip_client.py

# Set the entrypoint to run the Python script and forward arguments
ENTRYPOINT ["python3", "ntrip_client.py"]

# No default arguments
CMD []
