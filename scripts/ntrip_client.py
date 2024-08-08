#!/usr/bin/env python

import socket
import base64
import time
import logging
import yaml
import threading
import colorlog
from pyrtcm import RTCMReader

class NtripClient:
    def __init__(self, config_path):
        self.load_config(config_path)
        self.ntrip_socket = None
        self.gnss_socket = None
        self.ntrip_connected = False
        self.nmea_request_sent = False
        self.send_nmea_thread = None
        self.gnss_log_thread = None
        self.stop_event = threading.Event()

        # Configure logging with colors
        self.configure_logging()

    def configure_logging(self):
        """Configure logging with color support."""
        formatter = colorlog.ColoredFormatter(
            '%(asctime)s - %(log_color)s%(levelname)s%(reset)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(formatter)
        
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
            f"GET /{self.mountpoint} HTTP/1.1\r\n"
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
        
    def extract_gpgga_sentence(self, data):
        """Extract the GPGGA sentence from a given string."""
        sentences = data.splitlines()
        for sentence in sentences:
            if sentence.startswith('$GPGGA'):
                return sentence
        return ""
    
    def read_nmea_and_send_to_server(self):
        """Read incoming messages from the GNSS receiver."""
        while not self.stop_event.is_set():
            if not self.gnss_socket:
                logging.warning("GNSS socket not connected.")
                time.sleep(1)
                continue
            try:
                message = self.gnss_socket.recv(1024).decode()
                                
                if message:
                    if 'COM' in message:
                        logging.info(f'GNSS has ACK!')
                        continue
                    gpgga_sentence = self.extract_gpgga_sentence(message)
                    logging.info(f"Received GPGGA message: {gpgga_sentence}")
                    
                    self.send_nmea_to_ntrip_server(gpgga_sentence)
                    # logging.info(f'Received GNSS message: {message}')
                else:
                    logging.warning("No GNSS message received.")
            except socket.timeout:
                logging.warning("Socket timeout occurred while reading GNSS data.")
            except Exception as e:
                logging.error(f"Error reading GNSS data: {e}")
                continue
                # self.gnss_socket.close()
                # self.gnss_socket = None
                break

            time.sleep(1)

    def send_rtcm_to_gnss(self, rctm_sentence):
        """Send a RTCMv3 message to the GNSS receiver."""
        if self.gnss_socket:
            try:
                self.gnss_socket.send(rctm_sentence)
                logging.info(f"Sent RTCM  to GNSS receiver")
            except Exception as e:
                logging.error(f"Error sending command to GNSS receiver: {e}")
        else:
            logging.warning("GNSS socket not connected. Command not sent.")

    def generate_gga_sentence(self):
        """Generate NMEA GGA sentence."""
        lat_deg = int(self.fix_latitude)
        lat_min = (self.fix_latitude - lat_deg) * 60
        lat_hemisphere = 'N' if self.fix_latitude >= 0 else 'S'
        
        lon_deg = int(abs(self.fix_longitude))
        lon_min = (abs(self.fix_longitude) - lon_deg) * 60
        lon_hemisphere = 'E' if self.fix_longitude >= 0 else 'W'
        
        current_time = time.strftime("%H%M%S", time.gmtime())
        gga = f"GPGGA,{current_time},{lat_deg:02d}{lat_min:07.4f},{lat_hemisphere},{lon_deg:03d}{lon_min:07.4f},{lon_hemisphere},1,08,0.9,{self.fix_altitude:.1f},M,46.9,M,,"
        
        checksum = 0
        for char in gga:
            checksum ^= ord(char)
        checksum_hex = f"{checksum:02X}"
        
        return f"${gga}*{checksum_hex}"

    def send_nmea_to_ntrip_server(self, gpgga_sentence):
        """Send NMEA sentence to NTRIP server in a separate thread."""
        # while not self.stop_event.is_set():
        if not self.ntrip_connected:
            logging.warning("Not connected to NTRIP server. Cannot send NMEA.")
            time.sleep(1)
            return
        
        request = f"{gpgga_sentence}\r\n\r\n"
        try:
            self.ntrip_socket.send(request.encode())
            self.nmea_request_sent = True
            logging.info("Sent NMEA sentence to NTRIP server.")
        except Exception as e:
            logging.error(f"Error sending NMEA sentence: {e}")
            self.nmea_request_sent = False


    def read_rtcm_and_send_to_gnss(self):
        """Constantly check for new RTCMv3 data coming from the NTRIP server."""
        while self.ntrip_connected:
            if not self.nmea_request_sent:
                logging.info("NMEA request not sent. Skipping RTCM read.")
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
                    logging.info(f'Received RTCMv3 message with ID {rtcm_msg.identity}')
                    
                    self.send_rtcm_to_gnss(rtcm_msg.payload)
                    # logging.info(f'\tMsg:{rtcm_msg}')
                else:
                    logging.info("No RTCMv3 data received.")

            except socket.timeout:
                logging.warning("Socket timeout occurred while reading RTCMv3.")
                break
            except Exception as e:
                logging.error(f"Error reading RTCMv3 data: {e}")
                self.ntrip_connected = False
                break

            # time.sleep(1)

    def run(self):
        """Main execution loop."""
        if self.connect_ntrip_server():
            # Try to connect to gnss
            while(not self.connect_to_gnss()):
                continue
            
            try:
                # Start reading GNSS log in a separate thread
                self.gnss_log_thread = threading.Thread(target=self.read_nmea_and_send_to_server, daemon=True)
                self.gnss_log_thread.start()
                
                # # Start sending NMEA sentences in a separate thread
                # self.stop_event.clear()
                # self.send_nmea_thread = threading.Thread(target=self.send_nmea_to_ntrip_server, daemon=True)
                # self.send_nmea_thread.start()


                
                # Read RTCM data and send to the gnss in the main thread
                self.read_rtcm_and_send_to_gnss()

            except KeyboardInterrupt:
                logging.info("Interrupted by user. Disconnecting...")
            finally:
                self.stop_event.set()
                self.send_nmea_thread.join()
                self.gnss_log_thread.join()
                self.disconnect_ntrip_server()

if __name__ == "__main__":
    client = NtripClient(config_path='params.yaml')
    client.run()

