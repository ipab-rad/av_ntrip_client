#!/usr/bin/env python
"""
NTRIP Client for requesting and transmitting RTCMv3 corrections.

This script implements an NTRIP client for requesting and transmitting
RTCMv3 corrections to a Novatel GNSS receiver. It manages a single
connection to an NTRIP server and one to the Novatel GNSS receiver,
parses Novatel binary data, and handles RTCM messages.
"""

import argparse
import base64
import logging
import socket
import threading
import time
from collections import defaultdict

import colorlog

from nmea_generator import NMEAGenerator

from pyrtcm import RTCMReader, exceptions

import yaml


class NtripClient:
    """
    NTRIP client for requesting and transmitting RTCMv3 corrections.

    Manages a connection to an NTRIP server and a Novatel GNSS receiver.
    Handles parsing of Novatel binary data and RTCM messages, and supports
    options for using a fixed location and enabling debug logging.
    """

    def __init__(self, config_path, use_fix_location=False, debug_mode=False):
        """
        Initialise the object with configuration and settings.

        Loads settings from `config_path`, and sets up sockets, logging,
        and NMEA generator.

        Args:
            config_path (str): Path to the configuration file.
            use_fix_location (bool): Whether to use a fixed GPS location.
            debug_mode (bool): Whether to enable debug mode.
        """
        self.load_config(config_path)
        self.ntrip_socket = None
        self.gnss_socket = None
        self.ntrip_connected = False
        self.nmea_request_sent = False
        self.gnss_log_thread = None
        self.stop_event = threading.Event()
        self.use_fix_location = use_fix_location
        self.debug_mode = debug_mode
        self.received_rtcm_msgs_ids = defaultdict(int)
        # Novatel response offsets
        self.novatel_response_binary_dict = {
            'response_id': {'offset': 28, 'size': 4},
            'checksum': {'size': 4},
        }

        # Holds up to 255 values; load from JSON? (TODO)
        self.novatel_response_id_dict = {1: 'OK'}

        # Configure logging with colors
        self.configure_logging()

        # Create a NMEA generator for debugging
        self.nmea_generator = NMEAGenerator(
            self.fix_latitude, self.fix_longitude, self.fix_altitude
        )

    def configure_logging(self):
        """Configure logging with color support."""
        formatter = colorlog.ColoredFormatter(
            '%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(formatter)

        if self.debug_mode:
            logging.basicConfig(
                level=logging.DEBUG, handlers=[console_handler]
            )
        else:
            logging.basicConfig(level=logging.INFO, handlers=[console_handler])

    def load_config(self, config_path):
        """
        Load configuration from a YAML file.

        Reads the configuration file at `config_path` and sets instance
        variables for GNSS and NTRIP settings, including credentials.

        Args:
            config_path (str): Path to the YAML configuration file.
        """
        with open(config_path) as file:
            config = yaml.safe_load(file)
            self.gnss_host = config['gnss_host']
            self.gnss_port = config['gnss_port']
            self.ntrip_host = config['ntrip_host']
            self.ntrip_port = config['ntrip_port']
            self.mountpoint = config['mountpoint']
            self.username = config['username']
            self.password = config['password']
            self.fix_latitude = config['fix_latitude']
            self.fix_longitude = config['fix_longitude']
            self.fix_altitude = config['fix_altitude']
            self.chunk_size = config['chunk_size']

            self.credentials = base64.b64encode(
                f'{self.username}:{self.password}'.encode()
            ).decode()

    def connect_ntrip_server(self):
        """Connect to the NTRIP server."""
        self.ntrip_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ntrip_socket.settimeout(10)

        try:
            self.ntrip_socket.connect((self.ntrip_host, self.ntrip_port))
        except (OSError, socket.timeout) as e:
            logging.error(f'Unable to connect to NTRIP server: {e}')
            return False

        request = (
            f'GET /{self.mountpoint} HTTP/1.0\r\n'
            f'Host: {self.ntrip_host}\r\n'
            f'Ntrip-Version: Ntrip/1.0\r\n'
            f'User-Agent: NTRIP PythonClient/1.0\r\n'
            f'Authorization: Basic {self.credentials}\r\n'
            f'\r\n'
        )
        self.ntrip_socket.send(request.encode())

        try:
            response = self.ntrip_socket.recv(1024).decode('ISO-8859-1')
        except (OSError, socket.timeout) as e:
            logging.error(f'Error getting response from NTRIP: {e}')
            return False

        if any(
            success in response
            for success in ['ICY 200 OK', 'HTTP/1.0 200 OK', 'HTTP/1.1 200 OK']
        ):
            self.ntrip_connected = True
            logging.info('Connected to NTRIP server.')
            return True

        logging.error('Failed to connect to NTRIP server.')
        return False

    def disconnect_ntrip_server(self):
        """Disconnect from the NTRIP server."""
        self.ntrip_connected = False
        if self.ntrip_socket:
            try:
                self.ntrip_socket.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.timeout) as e:
                logging.error(f'Exception when shutting down the socket: {e}')
            try:
                self.ntrip_socket.close()
            except (OSError, socket.timeout) as e:
                logging.error(f'Exception when closing the socket: {e}')

    def connect_to_gnss(self):
        """Connect to the GNSS receiver."""
        self.gnss_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gnss_socket.settimeout(5)

        try:
            self.gnss_socket.connect((self.gnss_host, self.gnss_port))
            logging.info('Connected to GNSS receiver.')
            return True
        except (OSError, socket.timeout) as e:
            logging.error(f'Unable to connect to GNSS receiver: {e}')
            return False

    def configure_gnss(self):
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
                f'Configuration command sent to port: {self.gnss_port}'
            )

            # Read the response to confirm configuration
            response = self.gnss_socket.recv(1024).decode('utf-8')
            logging.info(f'GNSS configured with response: {response}')
        except (OSError, socket.timeout) as e:
            logging.error(f'Failed to send configuration: {e}')

    def parse_novatel_binary(self, data):
        """
        Parse Novatel binary data to log response IDs.

        Extracts and decodes the response ID from the binary data. Logs
        the decoded response ID or a warning if the ID is unknown.

        Args:
            data (bytes): Binary data from Novatel.
        """
        # Get response id information
        offset = self.novatel_response_binary_dict['response_id']['offset']
        end = offset + self.novatel_response_binary_dict['response_id']['size']
        # Decode response id into decimal number
        response_id = int.from_bytes(data[offset:end], byteorder='little')
        if response_id in self.novatel_response_id_dict:
            logging.debug(
                f'Novatel reply with: '
                f'{self.novatel_response_id_dict[response_id]}'
            )
        else:
            logging.warning(
                f'Novatel reply with unknown response id: {response_id}'
            )

    def split_data(self, data):
        """
        Split the input data into binary and ASCII messages.

        Process a byte sequence containing mixed binary and ASCII data.
        Extract and return the messages as separate lists.

        Args:
            data (bytes): Byte sequence with mixed data.

        Returns:
            tuple: (ascii_msgs, binary_msgs)
                - ascii_msgs (list): Extracted ASCII messages.
                - binary_msgs (list): Extracted binary messages.
        """
        # Define the headers
        binary_header = b'\xaaD\x12\x1c'
        ascii_start = b'$GP'

        # Initialize variables
        binary_msgs = []
        ascii_msgs = []

        i = 0
        length = len(data)

        while i < length:
            if data.startswith(binary_header, i):
                # Found the start of a binary message
                start = i
                i += len(binary_header)

                # Find the next binary header or ASCII start
                next_binary_index = data.find(binary_header, i)
                next_ascii_index = data.find(ascii_start, i)

                if next_binary_index == -1:
                    next_binary_index = length
                if next_ascii_index == -1:
                    next_ascii_index = length

                # Determine the end of the current binary message
                end = min(next_binary_index, next_ascii_index)

                # Extract and store the binary message
                binary_msgs.append(data[start:end])

                # Move index past this message
                i = end

            elif data.startswith(ascii_start, i):
                # Found the start of an ASCII message
                start = i
                # Find the end of this ASCII message
                end = data.find(b'\r\n', i)
                if end == -1:
                    # If no end delimiter is found,
                    #   process till the end of data
                    end = length
                else:
                    end += len(b'\r\n')
                # Extract and store the ASCII message
                ascii_msgs.append(data[start:end])
                # Move index past this message
                i = end

            else:
                # Move to the next byte if no start of a message is found
                i += 1

        return ascii_msgs, binary_msgs

    def read_nmea_and_send_to_server(self):
        """Read incoming messages from the GNSS receiver."""
        while not self.stop_event.is_set():
            # Check gnss connection
            if not self.gnss_socket:
                logging.warning('GNSS socket not connected.')
                time.sleep(1)
                continue
            try:
                message = self.gnss_socket.recv(1024)

                if message:

                    # Split msgs into binary and ascii like msgs
                    ascii_msgs, binary_msgs = self.split_data(message)

                    if ascii_msgs:
                        nmea_sentence = ''
                        # One of these ascii msgs should contain GPGGA data
                        for ascci_msg in ascii_msgs:
                            msg = ascci_msg.decode()
                            if 'GPGGA' in msg:
                                nmea_sentence += f'{msg}'

                        # If nmea sentences received, report back to
                        #  NTRIP server
                        if nmea_sentence:
                            logging.debug(
                                f'\nRecevied NMEA from GNSS:\n{nmea_sentence}'
                            )

                            if not self.use_fix_location:
                                self.send_nmea_to_ntrip_server(nmea_sentence)
                            else:
                                nmea_sentence = (
                                    self.nmea_generator.generate_gga_sentence()
                                )
                                self.send_nmea_to_ntrip_server(nmea_sentence)

                    if binary_msgs:
                        for binary_msg in binary_msgs:
                            self.parse_novatel_binary(binary_msg)
                else:
                    logging.warning('No GNSS message received.')
            except socket.timeout:
                logging.warning(
                    'Socket timeout occurred while reading GNSS data.'
                )
            except OSError as e:
                logging.error(f'Error reading GNSS data: {e}')
                logging.warning(f'Received: {message}')

            # time.sleep(1)

    def send_rtcm_to_gnss(self, rctm_sentence):
        """Send a RTCMv3 message to the GNSS receiver."""
        if self.gnss_socket:
            try:
                self.gnss_socket.send(rctm_sentence)
                logging.debug('Sent RTCM to GNSS receiver')
            except (OSError, socket.timeout) as e:
                logging.error(f'Error sending command to GNSS receiver: {e}')
        else:
            logging.warning('GNSS socket not connected. Command not sent.')

    def send_nmea_to_ntrip_server(self, nmea_sentence):
        """Send NMEA sentence to NTRIP server in a separate thread."""
        if not self.ntrip_connected:
            logging.warning('Not connected to NTRIP server. Cannot send NMEA.')
            time.sleep(1)
            return

        request = f'{nmea_sentence}\r\n'
        try:
            self.ntrip_socket.send(request.encode())
            self.nmea_request_sent = True
            logging.debug('NMEA sentence sent to NTRIP server.')
        except (OSError, socket.timeout) as e:
            logging.error(f'Error sending NMEA sentence: {e}')
            self.nmea_request_sent = False

    def read_rtcm_and_send_to_gnss(self):
        """Read RTCM data and report back to GNSS."""
        while self.ntrip_connected:
            if not self.nmea_request_sent:
                logging.debug('Waiting for client to send NMEA data.')
                time.sleep(1)
                continue

            try:
                server_response = b''
                while True:
                    chunk = self.ntrip_socket.recv(self.chunk_size)
                    server_response += chunk
                    if len(chunk) < self.chunk_size:
                        break

                if server_response:
                    if server_response[0] == 0xD3:
                        # Server response contains RTCM data
                        try:
                            rtcm_msg = RTCMReader.parse(server_response)
                            logging.debug(
                                f'RTCM received ID: {rtcm_msg.identity}'
                            )

                            # Keep track of rtcm msgs ids co
                            self.received_rtcm_msgs_ids[
                                int(rtcm_msg.identity)
                            ] += 1

                        except exceptions.RTCMParseError as e:
                            logging.warning(
                                f'Error parsing RTCM data: {e}\n'
                                f'Msg:\n {server_response}'
                            )

                    else:
                        logging.warning(
                            f'Non-RTCM msg received from Ntrip server:\n'
                            f'{server_response}'
                        )

                    # Send rtcm data to GNSS
                    self.send_rtcm_to_gnss(server_response)
                else:
                    logging.info('No RTCMv3 data received.')

            except socket.timeout:
                logging.warning(
                    'Ntrip server connection timeout occurred '
                    'while reading RTCMv3.'
                )
                self.ntrip_connected = False
                break

    def run(self):
        """Run main execution loop."""
        if self.connect_ntrip_server():
            # Try to connect to gnss
            while not self.connect_to_gnss():
                continue

            # Configure GNSS
            self.configure_gnss()

            try:
                # Start reading GNSS logs in a separate thread
                self.gnss_log_thread = threading.Thread(
                    target=self.read_nmea_and_send_to_server, daemon=True
                )
                self.gnss_log_thread.start()

                # Read RTCM data and send to the gnss in the main thread
                self.read_rtcm_and_send_to_gnss()

            except KeyboardInterrupt:
                logging.info('Interrupted by user. Disconnecting...')
                logging.debug(
                    f'\nReceived RTCM msgs types:\n'
                    f'{self.received_rtcm_msgs_ids}'
                )
            finally:
                self.stop_event.set()
                self.gnss_log_thread.join()
                self.disconnect_ntrip_server()


if __name__ == '__main__':
    # Initialize the argument parser
    parser = argparse.ArgumentParser(description='Ntrip Client')

    # Add arguments
    parser.add_argument(
        '--use-fix-location',
        action='store_true',
        help='Use fixed location for Ntrip Client',
    )
    parser.add_argument(
        '--debug', action='store_true', help='Enable debug mode'
    )

    # Parse the arguments
    args = parser.parse_args()

    # Create NtripClient
    client = NtripClient(
        config_path='params.yaml',
        use_fix_location=args.use_fix_location,
        debug_mode=args.debug,
    )

    # Run client
    client.run()
