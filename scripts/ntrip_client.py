#!/usr/bin/env python

import socket
import base64
import time
import logging
import yaml
import threading
import colorlog
import argparse

from collections import defaultdict
from pyrtcm import RTCMReader

from nmea_generator import NMEAGenerator


class NtripClient:
    def __init__(self, config_path, use_fix_location=False, debug_mode=False):
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
            'response_id': {
                'offset': 28,
                'size': 4
            },
            'checksum': {
              'size': 4  
            }
        }
        
        # This dictionary can contain 255 values, best to load them from a JSON file
        self.novatel_response_id_dict = {
            1: 'OK'
        }
        
        # Configure logging with colors
        self.configure_logging()
        
        # Create a NMEA generator for debugging
        self.nmea_generator = NMEAGenerator(
            self.fix_latitude, self.fix_longitude, self.fix_altitude)
        
    def configure_logging(self):
        """Configure logging with color support."""
        formatter = colorlog.ColoredFormatter(
            '%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(formatter)
        
        if self.debug_mode:
            logging.basicConfig(level=logging.DEBUG, handlers=[console_handler])
        else:
            logging.basicConfig(level=logging.INFO, handlers=[console_handler])

    def load_config(self, config_path):
        with open(config_path, 'r') as file:
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

            self.credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()

    def connect_ntrip_server(self):
        """Connect to the NTRIP server."""
        self.ntrip_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ntrip_socket.settimeout(5)

        try:
            self.ntrip_socket.connect((self.ntrip_host, self.ntrip_port))
        except Exception as e:
            logging.error(f'Unable to connect to NTRIP server: {e}')
            return False

        request = (
            f"GET /{self.mountpoint} HTTP/1.0\r\n"
            f"Host: {self.ntrip_host}\r\n"
            f"Ntrip-Version: Ntrip/1.0\r\n"
            f"User-Agent: NTRIP PythonClient/1.0\r\n"
            f"Authorization: Basic {self.credentials}\r\n"
            f"\r\n"
        )
        self.ntrip_socket.send(request.encode())

        try:
            response = self.ntrip_socket.recv(1024).decode('ISO-8859-1')
        except Exception as e:
            logging.error(f"Error getting response from NTRIP: {e}")
            return False

        if any(success in response for success in ['ICY 200 OK', 'HTTP/1.0 200 OK', 'HTTP/1.1 200 OK']):
            self.ntrip_connected = True
            logging.info("Connected to NTRIP server.")
            return True

        logging.error("Failed to connect to NTRIP server.")
        return False

    def disconnect_ntrip_server(self):
        """Disconnect from the NTRIP server."""
        self.ntrip_connected = False
        if self.ntrip_socket:
            try:
                self.ntrip_socket.shutdown(socket.SHUT_RDWR)
            except Exception as e:
                logging.error(f'Exception when shutting down the socket: {e}')
            try:
                self.ntrip_socket.close()
            except Exception as e:
                logging.error(f'Exception when closing the socket: {e}')

    def connect_to_gnss(self):
        """Connect to the GNSS receiver."""
        self.gnss_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gnss_socket.settimeout(5)

        try:
            self.gnss_socket.connect((self.gnss_host, self.gnss_port))
            logging.info("Connected to GNSS receiver.")
            return True
        except Exception as e:
            logging.error(f'Unable to connect to GNSS receiver: {e}')
            return False
    
    def parse_novatel_binary(self,data):
        
        # Get response id information
        offset = self.novatel_response_binary_dict['response_id']['offset']
        end = offset + self.novatel_response_binary_dict['response_id']['size']
        # Decode reponse id into decimal number
        response_id = int.from_bytes(data[offset:end], byteorder='little')
        if  response_id in self.novatel_response_id_dict:
            logging.debug(f'Novatel reply with: {self.novatel_response_id_dict[response_id]}')     
        else:
            logging.warning(f'Novatel reply with unknown response id: {response_id}')
    
    def split_data(self,data):
        # Define the headers
        binary_header = b'\xaaD\x12\x1c'
        ascii_start = b'$GP'

        # Initialize variables
        messages = []
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
                    # If no end delimiter is found, process till the end of data
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
                logging.warning("GNSS socket not connected.")
                time.sleep(1)
                continue
            try:
                message = self.gnss_socket.recv(1024)
                
                if message:
                                    
                    # Split msgs into binay and ascii like msgs
                    ascii_msgs, binary_msgs = self.split_data(message)
                    
                    if ascii_msgs:
                        nmea_sentence = ''
                        # One of these ascii msgs should contain GPGGA data
                        for ascci_msg in ascii_msgs:
                            msg = ascci_msg.decode()
                            if 'GPGGA' in msg:
                                nmea_sentence += f'{msg}'
                        
                        # If we received nmea sentences report back to NTRIP server
                        if nmea_sentence:
                            logging.debug(f'\nRecevied NMEA from GNSS:\n{nmea_sentence}')
                            
                            if not self.use_fix_location:
                                self.send_nmea_to_ntrip_server(nmea_sentence)
                            else:
                                # nmea_sentence = self.nmea_generator.get_fix_nmea_sentences()
                                nmea_sentence = self.nmea_generator.generate_gga_sentence()
                                self.send_nmea_to_ntrip_server(nmea_sentence)
                                       
                    if binary_msgs:
                        for binary_msg in binary_msgs:
                            self.parse_novatel_binary(binary_msg)
                else:
                    logging.warning("No GNSS message received.")
            except socket.timeout:
                logging.warning("Socket timeout occurred while reading GNSS data.")
            except Exception as e:
                logging.error(f"Error reading GNSS data: {e}")
                logging.warning(f'Received: {message}')
                    
                
            # time.sleep(1)

    def send_rtcm_to_gnss(self, rctm_sentence):
        """Send a RTCMv3 message to the GNSS receiver."""
        if self.gnss_socket:
            try:
                self.gnss_socket.send(rctm_sentence)
                logging.debug(f"Sent RTCM  to GNSS receiver")
            except Exception as e:
                logging.error(f"Error sending command to GNSS receiver: {e}")
        else:
            logging.warning("GNSS socket not connected. Command not sent.")

    def send_nmea_to_ntrip_server(self, nmea_sentence):
        """Send NMEA sentence to NTRIP server in a separate thread."""
        if not self.ntrip_connected:
            logging.warning("Not connected to NTRIP server. Cannot send NMEA.")
            time.sleep(1)
            return
        
        request = f"{nmea_sentence}\r\n"
        try:
            self.ntrip_socket.send(request.encode())
            self.nmea_request_sent = True
            logging.debug("NMEA sentence sent to NTRIP server.")
        except Exception as e:
            logging.error(f"Error sending NMEA sentence: {e}")
            self.nmea_request_sent = False
    
    def read_rtcm_and_send_to_gnss(self):
        """Constantly check for new RTCMv3 data coming from the NTRIP server."""
        while self.ntrip_connected:
            if not self.nmea_request_sent:
                logging.debug("Waiting for client to send NMEA data.")
                time.sleep(1)
                continue
            
            try:
                rtcm_res = b''
                while True:
                    chunk = self.ntrip_socket.recv(self.chunk_size)
                    rtcm_res += chunk
                    if len(chunk) < self.chunk_size:
                        break

                if rtcm_res:
                    
                    rtcm_msg = RTCMReader.parse(rtcm_res)
                    logging.debug(f'RTCM received ID: {rtcm_msg.identity}')
                    
                    # Keep track of rtcm msgs ids count
                    self.received_rtcm_msgs_ids[int(rtcm_msg.identity)] += 1 
                                            
                    # Send RCTM to GNSS                                 
                    self.send_rtcm_to_gnss(rtcm_res)
                else:
                    logging.info("No RTCMv3 data received.")

            except socket.timeout:
                logging.warning("Socket timeout occurred while reading RTCMv3.")
                break
            except Exception as e:
                logging.error(f"Error reading RTCMv3 data: {e}")
                self.ntrip_connected = False
                break


    def run(self):
        """Main execution loop."""
        if self.connect_ntrip_server():
            # Try to connect to gnss
            while(not self.connect_to_gnss()):
                continue
            
            try:
                # Start reading GNSS logs in a separate thread
                self.gnss_log_thread = threading.Thread(target=self.read_nmea_and_send_to_server, daemon=True)
                self.gnss_log_thread.start()
                
                # Read RTCM data and send to the gnss in the main thread
                self.read_rtcm_and_send_to_gnss()

            except KeyboardInterrupt:
                logging.info("Interrupted by user. Disconnecting...")
                logging.debug(f'\nReceived RTCM msgs types:\n{self.received_rtcm_msgs_ids}')
            finally:
                self.stop_event.set()
                self.gnss_log_thread.join()
                self.disconnect_ntrip_server()

if __name__ == "__main__":
    # Initialize the argument parser
    parser = argparse.ArgumentParser(description="Ntrip Client")

    # Add arguments
    parser.add_argument('--use-fix-location', action='store_true', help='Use fixed location for Ntrip Client')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    # Parse the arguments
    args = parser.parse_args()    
    
    client = NtripClient(config_path='params.yaml', use_fix_location=args.use_fix_location, debug_mode=args.debug)
    client.run()