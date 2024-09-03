"""
NMEA generator module.

This module generates NMEA (GPGGA) sentence for GPS data simulation.
"""

import time


class NMEAGenerator:
    """
    A class to generate NMEA GPGGA sentence.

    It provides methods to generate and validate GPGGA
    sentences.
    """

    def __init__(self, fix_latitude, fix_longitude, fix_altitude):
        """Initialise class."""
        self.fix_latitude = fix_latitude
        self.fix_longitude = fix_longitude
        self.fix_altitude = fix_altitude

    def _calculate_checksum(self, nmea_str):
        """Calculate the NMEA checksum."""
        checksum = 0
        for char in nmea_str:
            checksum ^= ord(char)
        return f'{checksum:02X}'

    def generate_gga_sentence(self):
        """Generate NMEA GGA sentence."""
        lat_deg = int(self.fix_latitude)
        lat_min = (self.fix_latitude - lat_deg) * 60
        lat_hemisphere = 'N' if self.fix_latitude >= 0 else 'S'

        lon_deg = int(abs(self.fix_longitude))
        lon_min = (abs(self.fix_longitude) - lon_deg) * 60
        lon_hemisphere = 'E' if self.fix_longitude >= 0 else 'W'

        current_time = time.strftime('%H%M%S', time.gmtime())
        gga = (
            f'GPGGA,{current_time},{lat_deg:02d}{lat_min:07.4f},'
            f'{lat_hemisphere},{lon_deg:03d}{lon_min:07.4f},'
            f'{lon_hemisphere},1,08,0.9,{self.fix_altitude:.1f},M,46.9,M,,'
        )

        checksum = self._calculate_checksum(gga)
        return f'${gga}*{checksum}'

    def is_gpgga_data_valid(self, nmea_sentence: str) -> bool:
        """Validate GPGGA data."""
        try:
            # Split the sentence into its components
            fields = nmea_sentence.split(',')

            # Check the length of the fields, should be 14 or 15
            if len(fields) < 14 or len(fields) > 15:
                return False

            # Validate GPS quality indicator (field 6)
            gps_qual = int(fields[6])
            if gps_qual == 0:
                # If 0, data is not valid/reliable
                return False

            # If all validations passed, return True
            return True

        except (IndexError, ValueError):
            return False
