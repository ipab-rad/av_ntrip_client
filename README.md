# av_ntrip_client

NTRIP client for RTK corrections in the AV's GNSS system.

## Overview

`av_ntrip_client` is a tool designed to connect the IPAB Autonomous Vehicle's Novatel PwrPak7d GNSS to the Smartnet NTRIP server, providing Real-Time Kinematic (RTK) corrections to enhance GNSS accuracy. The client is containerised using Docker for ease of deployment and use.

## Features

- Connects to the Smartnet NTRIP server for RTK corrections.
- Supports live GNSS GPS reading or fixed location data.
- Logs generated for troubleshooting and analysis.

## Setup

1. **Clone the Repository:**

   - **For General Public:**
     ```bash
     git clone https://github.com/ipab-rad/av_ntrip_client.git
     ```

   - **For Authorised Users:**
     If you have authorised access to the `av_ntrip_client` repository, use:
     ```bash
     git clone --recurse-submodules git@github.com:ipab-rad/av_ntrip_client.git
     ```

2. **Build and Run the Docker Container:**

   - **Development Mode:**
     This mode mounts the current `scripts` directory into the container, allowing for live development.
     ```bash
     ./dev.sh
     ```

   - **Runtime Mode:**
     This mode builds the Docker container and runs it with the specified options. The script will automatically start `ntrip_client.py`. You can pass arguments such as `--use-fix-location` `--debug` or `--help`.
     ```bash
     ./runtime.sh [options]
     ```
     - Example:
       ```bash
       ./runtime.sh --use-fix-location --debug
       ```
## Usage

Once the container is running, `ntrip_client.py` will automatically connect to the Smartnet NTRIP server using the provided credentials. Logs will be saved in the `scripts/logs` directory.

## NTRIP Server Credentials

The `scripts/av_ntrip_credentials` directory is a protected submodule due to licensing requirements of the Smartnet service. Access is restricted to authorised personnel only.

## License

This project is licensed under the terms of the Apache-2.0 [LICENCE](./LICENSE) file.

## Contact

For any issues or questions, please contact [Alejandor Bordallo](https://github.com/GreatAlexander) or [Hector Cruz](https://github.com/hect95)
