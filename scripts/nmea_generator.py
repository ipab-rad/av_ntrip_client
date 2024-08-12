import time

class NMEAGenerator:
    def __init__(self, fix_latitude, fix_longitude, fix_altitude):
        self.fix_latitude = fix_latitude
        self.fix_longitude = fix_longitude
        self.fix_altitude = fix_altitude

    def _calculate_checksum(self, nmea_str):
        """Calculate the NMEA checksum."""
        checksum = 0
        for char in nmea_str:
            checksum ^= ord(char)
        return f"{checksum:02X}"

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
        
        checksum = self._calculate_checksum(gga)
        return f"${gga}*{checksum}"

    def generate_rmc_sentence(self):
        """Generate NMEA RMC sentence."""
        current_time = time.strftime("%H%M%S", time.gmtime())
        current_date = time.strftime("%d%m%y", time.gmtime())
        
        lat_deg = int(self.fix_latitude)
        lat_min = (self.fix_latitude - lat_deg) * 60
        lat_hemisphere = 'N' if self.fix_latitude >= 0 else 'S'
        
        lon_deg = int(abs(self.fix_longitude))
        lon_min = (abs(self.fix_longitude) - lon_deg) * 60
        lon_hemisphere = 'E' if self.fix_longitude >= 0 else 'W'
        
        rmc = f"GPRMC,{current_time},A,{lat_deg:02d}{lat_min:07.4f},{lat_hemisphere},{lon_deg:03d}{lon_min:07.4f},{lon_hemisphere},000.0,360.0,{current_date},,"

        checksum = self._calculate_checksum(rmc)
        return f"${rmc}*{checksum}"

    def generate_gst_sentence(self):
        """Generate NMEA GST sentence."""
        current_time = time.strftime("%H%M%S", time.gmtime())
        # Example values, these would typically come from actual GNSS data
        rms_err = 0.0
        semi_major_dev = 0.0
        semi_minor_dev = 0.0
        orient = 0.0
        lat_err_dev = 0.0
        lon_err_dev = 0.0
        alt_err_dev = 0.0
        
        gst = (f"GPGST,{current_time},{rms_err:.1f},{semi_major_dev:.1f},{semi_minor_dev:.1f},"
               f"{orient:.1f},{lat_err_dev:.1f},{lon_err_dev:.1f},{alt_err_dev:.1f}")
        
        checksum = self._calculate_checksum(gst)
        return f"${gst}*{checksum}"

    def get_fix_nmea_sentences(self):
        """Generate and return NMEA sentences as a dictionary."""
        # return {
        #     "GPGGA": self.generate_gga_sentence(),
        #     "GPRMC": self.generate_rmc_sentence(),
        #     "GPGST": self.generate_gst_sentence()
        # }

        sentences = (
            f"{self.generate_gga_sentence()}\r\n"
            f"{self.generate_rmc_sentence()}\r\n"
            f"{self.generate_gst_sentence()}\r\n"
        )
        return sentences