#!/usr/bin/env python
"""
Novatel Client module.

This script connects to a Novatel GNSS receiver, configures it, and logs the
received data.
"""

import argparse
import logging
import socket

import colorlog


class NovatelClient:
    """Client to interact with a Novatel GNSS receiver."""

    def __init__(self, gnss_ip, gnss_port):
        """Initialise NovatelClient with the GNSS receiver's IP and port."""
        self.gnss_ip = gnss_ip
        self.gnss_port = gnss_port
        self.gnss_socket = None
        self.port_name = None

    def connect(self):
        """Connect to the GNSS receiver via TCP."""
        try:
            self.gnss_socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM
            )
            self.gnss_socket.connect((self.gnss_ip, self.gnss_port))
            logging.info(
                f'Connected to GNSS receiver at '
                f'{self.gnss_ip}:{self.gnss_port}'
            )

        except (OSError, socket.timeout) as e:
            logging.error(f'Failed to connect: {e}')

    def configure_port(self):
        """Configure the GNSS port to log NMEA data."""
        configure_command = (
            '\r\n'
            'unlogall thisport\r\n'
            'log gpggalong ontime 0.1\r\n'
            'log gprmc ontime 0.1\r\n'
            'log gpgst ontime 0.2\r\n'
            'interfacemode rtcmv3 novatel\r\n'  # Set RX and TX
        )

        try:
            self.gnss_socket.sendall(configure_command.encode('utf-8'))
            logging.info(
                f'Sent configuration commands to port: {self.gnss_port}'
            )

            # Read the response to confirm configuration
            response = self.gnss_socket.recv(1024).decode('utf-8')
            logging.info(f'Response from GNSS: {response}')
        except (OSError, socket.timeout) as e:
            logging.error(f'Failed to send configuration: {e}')

    def close_connection(self):
        """Close the connection to the GNSS receiver."""
        if self.gnss_socket:
            try:
                self.gnss_socket.close()
                logging.info('Closed connection to GNSS receiver')
            except OSError as e:
                logging.error(f'Failed to close connection: {e}')


if __name__ == '__main__':
    # Initialize the argument parser
    parser = argparse.ArgumentParser(description='Novatel Client')

    # Add the port argument with a default value of 3005
    parser.add_argument(
        '--port',
        type=int,
        default=3003,
        help='GNSS port number to connect and configure',
    )

    # Parse the arguments
    args = parser.parse_args()

    # Access the port number
    port_number = args.port

    # Configure logging
    formatter = colorlog.ColoredFormatter(
        '%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    console_handler = colorlog.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console_handler])

    # Replace with your GNSS receiver's IP and port
    client = NovatelClient(gnss_ip='172.31.0.90', gnss_port=port_number)

    try:
        client.connect()
        client.configure_port()

        while True:
            try:
                # Receive the initial message to identify the ICOM port name
                msg = client.gnss_socket.recv(1024)
                logging.info(f'From GNSS: {msg.decode()}')

            except (OSError, socket.timeout) as e:
                logging.error(f'Failed to connect: {e}')
                break  # Exit the loop on error

    except KeyboardInterrupt:
        logging.info('Interruption shutting down...')

    finally:
        client.close_connection()
        logging.info('Connection closed. Exiting.')
