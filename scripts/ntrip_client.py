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
from datetime import datetime

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
        self.ntrip_socket = None
        self.gnss_socket = None
        self.ntrip_connected = False
        self.nmea_request_sent = False
        self.gnss_log_thread = None
        self.stop_event = threading.Event()
        self.use_fix_location = use_fix_location
        self.debug_mode = debug_mode
        self.received_rtcm_msgs_ids = defaultdict(int)
        self.latest_nmea_data_valid = False
        self.novatel_response_binary_dict = {
            'response_id': {'offset': 28, 'size': 4},
            'checksum': {'size': 4},
        }
        self.NOVATEL_OK_ID = 1
        self.SOCKET_BUFFER_SIZE = 2048
        # Indicates the start of an RTCM message
        self.RTCM_DATA_PREAMBLE = 0xD3
        self.PAUSE_DURATION = 1.0

        self.configure_logging()

        self.load_config(config_path)

        self.nmea_generator = NMEAGenerator(
            self.fix_latitude, self.fix_longitude, self.fix_altitude
        )

    def configure_logging(self):
        """Configure logging to support color and timestamped log file."""
        # Define the log format for the console
        formatter = colorlog.ColoredFormatter(
            '%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

        # Create a console handler with the colored formatter
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(formatter)

        # Define the log format for the file
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

        # Generate a timestamped log file name
        timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        log_filename = f'logs/{timestamp}_ntrip_client.log'

        # Create a file handler with the log filename and formatter
        file_handler = logging.FileHandler(log_filename)
        file_handler.setFormatter(file_formatter)

        # Determine the logging level based on debug_mode
        if self.debug_mode:
            logging.basicConfig(
                level=logging.DEBUG, handlers=[console_handler, file_handler]
            )
        else:
            logging.basicConfig(
                level=logging.INFO, handlers=[console_handler, file_handler]
            )

    def load_config(self, config_path):
        """
        Load configuration from a YAML file.

        Reads the configuration file at `config_path` and sets instance
        variables for GNSS and NTRIP settings, including credentials.

        Args:
            config_path (str): Path to the YAML configuration file.
        """
        try:
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

                self.credentials = base64.b64encode(
                    f'{self.username}:{self.password}'.encode()
                ).decode()

        except FileNotFoundError:
            logging.error(
                f'Configuration file at {config_path} does not exist.'
            )
            raise SystemExit()
        except yaml.YAMLError as e:
            logging.error(f'Error parsing the configuration file: {e}')
            raise SystemExit()
        except KeyError as e:
            logging.error(f'Missing required YAML parameter: {e}')
            raise SystemExit()

    def connect_ntrip_server(self):
        """Connect to the NTRIP server."""
        self.ntrip_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ntrip_socket.settimeout(6)

        logging.info(
            f'Attempting to connect to NTRIP server at'
            f' {self.ntrip_host}:{self.ntrip_port}'
        )

        try:
            self.ntrip_socket.connect((self.ntrip_host, self.ntrip_port))
        except socket.gaierror as e:
            logging.error(
                'Unable to connect to NTRIP server:'
                f' DNS resolution failed: {e}'
            )
            return False
        except socket.timeout:
            logging.error(
                'Unable to connect to NTRIP server: Connection timed out'
            )
            return False
        except OSError as e:
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
            response = self.ntrip_socket.recv(self.SOCKET_BUFFER_SIZE).decode(
                'ISO-8859-1'
            )
        except (OSError, socket.timeout) as e:
            logging.error(f'Error getting response from NTRIP: {e}')
            return False

        if any(
            success in response
            for success in ['ICY 200 OK', 'HTTP/1.0 200 OK', 'HTTP/1.1 200 OK']
        ):
            self.ntrip_connected = True
            logging.info('Successfully connected to NTRIP server.')
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

        logging.info(
            f'Attempting to connect to GNSS receiver at'
            f' {self.gnss_host}:{self.gnss_port}'
        )

        try:
            self.gnss_socket.connect((self.gnss_host, self.gnss_port))
            logging.info('Successfully connected to GNSS receiver.')
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

        logging.debug(f'Configuring GNSS {self.gnss_port} port')

        try:
            self.gnss_socket.sendall(configure_command.encode('utf-8'))

            # Read the response to confirm configuration
            response = self.gnss_socket.recv(self.SOCKET_BUFFER_SIZE).decode(
                'utf-8'
            )
            logging.info('GNSS receiver successfully configured.')
            logging.debug(f'GNSS response: {response}')
        except (OSError, socket.timeout) as e:
            logging.error(f'Failed to send configuration: {e}')

    def parse_novatel_binary(self, data):
        """
        Parse Novatel binary data to log response IDs.

        Extracts and decodes the response ID from the binary data. Logs
        the decoded response ID or a warning if the ID is unknown.

        This is based on Table 10 (1.5.3 Binary Response) of
        Novatel OEM7 Command and Logs Manual (Rev: v1)

        Args:
            data (bytes): Binary data from Novatel.
        """
        # Extract relevant metadata from the response dictionary
        resp_info = self.novatel_response_binary_dict['response_id']
        resp_id_end = resp_info['offset'] + resp_info['size']
        checksum_size = self.novatel_response_binary_dict['checksum']['size']

        # Decode the response ID
        resp_id = int.from_bytes(
            data[resp_info['offset'] : resp_id_end],  # noqa: E203
            byteorder='little',
        )

        # Extract the remaining response content, excluding the checksum
        resp = data[resp_id_end:-checksum_size]  # noqa: E203

        # Log the response based on the response ID
        if resp_id == self.NOVATEL_OK_ID:
            logging.debug(f'GNSS response: {resp.decode()}')
        else:
            logging.warning(
                f'GNSS returned an unexpected response: {resp.decode()}'
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

            if not self.gnss_socket:
                logging.warning('GNSS socket not connected.')
                time.sleep(self.PAUSE_DURATION)
                continue

            try:
                message = self.gnss_socket.recv(self.SOCKET_BUFFER_SIZE)
                if not message:
                    logging.warning('Empty msg received from GNSS')
                    continue

                # Split messages into binary and ASCII types
                ascii_msgs, binary_msgs = self.split_data(message)

                # Get GPGGA msg from ASCII msgs
                nmea_sentence = next(
                    (msg.decode() for msg in ascii_msgs if b'GPGGA' in msg),
                    None,
                )

                if nmea_sentence:
                    # logging.debug(
                    #     f'NMEA data received from GNSS: {nmea_sentence}'
                    # )

                    if self.use_fix_location:
                        generated_sentence = (
                            self.nmea_generator.generate_gga_sentence()
                        )
                        self.latest_nmea_data_valid = True
                        self.send_nmea_to_ntrip_server(generated_sentence)
                    else:

                        self.latest_nmea_data_valid = (
                            self.nmea_generator.is_gpgga_data_valid(
                                nmea_sentence
                            )
                        )

                        if self.latest_nmea_data_valid:
                            self.send_nmea_to_ntrip_server(nmea_sentence)
                        else:
                            logging.debug(
                                'NMEA data is not valid. '
                                'Skipping sending it to NTRIP server.'
                            )

                # Process binary messages
                for binary_msg in binary_msgs:
                    self.parse_novatel_binary(binary_msg)

            except socket.timeout:
                logging.warning(
                    'Socket timeout occurred while reading GNSS data.'
                )
            except OSError as e:
                logging.error(f'Error reading GNSS data: {e}')
                logging.warning(f'Received: {message}')

    def send_rtcm_to_gnss(self, rctm_sentence):
        """Send a RTCMv3 message to the GNSS receiver."""
        if self.gnss_socket:
            try:
                self.gnss_socket.send(rctm_sentence)
                logging.debug('RTCM message sent to GNSS')

            except (OSError, socket.timeout) as e:
                logging.error(f'Error sending command to GNSS receiver: {e}')
        else:
            logging.warning('GNSS socket not connected. Command not sent.')

    def send_nmea_to_ntrip_server(self, nmea_sentence):
        """Send NMEA sentence to NTRIP server in a separate thread."""
        if not self.ntrip_connected:
            logging.debug('Not connected to NTRIP server. Cannot send NMEA.')
            time.sleep(self.PAUSE_DURATION)
            return

        request = f'{nmea_sentence}\r\n'
        try:
            self.ntrip_socket.send(request.encode())
            self.nmea_request_sent = True
            # logging.debug('NMEA message sent to NTRIP server.')
        except (OSError, socket.timeout) as e:
            logging.error(
                f'Error sending NMEA sentence to NTRIP server: {e}'
                f'\nAttempting to reconnect..'
            )
            self.nmea_request_sent = False
            self.ntrip_connected = False

    def is_rtcm_data(self, response_data):
        """Check if data is RTCM correction."""
        return response_data[0] == self.RTCM_DATA_PREAMBLE

    def read_rtcm_and_send_to_gnss(self):
        """Read RTCM data and report back to GNSS."""
        try:
            server_response = self.ntrip_socket.recv(self.SOCKET_BUFFER_SIZE)

            if not server_response:
                logging.warning('NTRIP server replied with an empty message')
                time.sleep(self.PAUSE_DURATION)
                return

            if self.is_rtcm_data(server_response):

                try:
                    rtcm_msg = RTCMReader.parse(server_response)
                    logging.debug(
                        f'RTCM data (ID: {rtcm_msg.identity}) received'
                    )

                    # Keep track of RTCM message IDs
                    self.received_rtcm_msgs_ids[int(rtcm_msg.identity)] += 1

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

            self.send_rtcm_to_gnss(server_response)

        except socket.timeout:
            logging.warning(
                'NTRIP server connection lost due to '
                'timeout while reading RTCMv3. '
                'Attempting to reconnect...'
            )
            self.ntrip_connected = False

    def run(self):
        """Run main execution loop."""
        while not self.connect_to_gnss():
            time.sleep(self.PAUSE_DURATION)
            continue

        self.configure_gnss()

        try:
            # Start reading GNSS logs in a separate thread
            self.gnss_log_thread = threading.Thread(
                target=self.read_nmea_and_send_to_server, daemon=True
            )
            self.gnss_log_thread.start()

            while True:
                if not self.ntrip_connected:
                    if not self.connect_ntrip_server():
                        time.sleep(self.PAUSE_DURATION)
                        continue

                if not self.latest_nmea_data_valid:
                    logging.debug(
                        'Waiting to receive valid NMEA data from GNSS ...'
                    )
                    time.sleep(self.PAUSE_DURATION)
                    continue

                if not self.nmea_request_sent:
                    logging.debug(
                        'Waiting for client to send valid NMEA data.'
                    )
                    time.sleep(self.PAUSE_DURATION)
                    continue

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

    parser = argparse.ArgumentParser(description='Ntrip Client')
    parser.add_argument(
        '--param-file',
        default='av_ntrip_credentials/smartnet_novatel_params.yaml',
        help='Path to the YAML file containing Ntrip server credentials',
    )
    parser.add_argument(
        '--use-fix-location',
        action='store_true',
        help='Use fixed location for Ntrip requests',
    )
    parser.add_argument(
        '--debug', action='store_true', help='Enable debug mode'
    )

    args = parser.parse_args()

    client = NtripClient(
        config_path=args.param_file,
        use_fix_location=args.use_fix_location,
        debug_mode=args.debug,
    )

    client.run()
