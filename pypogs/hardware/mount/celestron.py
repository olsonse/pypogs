"""
Implementation of a serially connected Celestron mount.
"""

from . import serial
from .util import *

class Mount(serial.Mount):
    baud = 9600
    eol_byte = b'#'
    port_test = dict(
      command='m',
      response_regex = rb'#(\s+|.)$',
    )
    known_tracking_modes = {'sidereal', 'custom'}

    # FIXME:  look these up?  Can these be queried?
    hardware_max_rates = None, None
    hardware_altitude_limits = None, None
    hardware_azimuth_limits = None, None

    @property
    def tracking_mode(self):
        """
        Return the current tracking mode of the mount.  This return value should
        generally be taken from one of the following:
          - sidereal
          - solar
          - lunar
          - custom
        """
        tracking_mode = self.query_command('t')
        return 'sidereal' if tracking_mode != None and tracking_mode[0] == '1' \
               else 'custom'

    @tracking_mode.setter
    def tracking_mode(self, value):
        if value == 'sidereal':
            assert self.query_command('T1') is not None, \
              'Mount did not acknowledge!'
            # not sure why the original code used thread to do something not in
            # parallel:
            # success = [False]
            # def _set_tracking_on(success):
            #     #self._serial_send_bytes_command([ord('T'),1])
            #     #assert self._serial_check_ack(ord('#')), 'Mount did not acknowledge!'
            #     assert self._serial_query('T1') is not None, 'Mount did not acknowledge!'
            #     success[0] = True
            #     self._is_sidereal_tracking = True
            # t = Thread(target=_set_tracking_on, args=(success,))
            # t.start()
            # t.join()
            # assert success[0], 'Failed communicating with mount'
            # self._is_sidereal_tracking = True
        elif value == 'custom':
            self.cel_tracking_off()
        else:
            raise ValueError(f'Do not know how to set tracking_mode="{value}"')

    def cel_tracking_off(self):
        """Disable sidreal tracking on celestron mount."""
        # not sure why the original code used thread to do something not in
        # parallel:
        #success = [False]
        #def _set_tracking_off(success):
        #    self._serial_send_bytes_command([ord('T'),0])
        #    assert self._serial_check_ack(), 'Mount did not acknowledge!'
        #    success[0] = True
        #t = Thread(target=_set_tracking_off, args=(success,))
        #t.start()
        #t.join()
        #assert success[0], 'Failed communicating with mount'
        self.send_bytes_command(b'T\0')
        assert self.check_ack(), 'Mount did not acknowledge!'

    def _initialize(self):
        """Initialise (make ready to start) the device. The model and identity
        must be defined.
        """
        assert not self.serial_is_open, 'Serial port already open'
        assert self.identity is not None, 'Define identity before initialising'
        self._logger.debug('Using %s, try to initialise', self.model)
        self._logger.debug('Opening serial port "%s"', self.identity)
        self.open()
        self._logger.debug('Opened serial port, sending test command')
        res = self.query_command('m')
        self._logger.debug('Mount responded with: "%s"', res)
        self._logger.debug('Set tracking to off')
        self.cel_tracking_off()

    def _movement_active(self):
        """
        Returns True if the mount can natively report that it has active motion.

        Generally should only be called by self.is_moving.
        """
        self._logger.debug('Using celestron, asking if moving')
        # not sure why the original code used thread to do something not in
        # parallel:
        #ret = [None]
        #def _is_moving_to(ret):
        #    self.send_text_command('L')
        #    ret[0] = self.read_to_eol()
        #t = Thread(target=_is_moving_to, args=(ret,))
        #t.start()
        #t.join()
        #moving = not ret[0] == b'0'
        #self._logger.debug('Mount returned "%s", is moving: %s', ret[0], moving)

        self.send_text_command('L')
        ret = self.read_to_eol()
        moving = ret != b'0'
        self._logger.debug('Mount returned "%s", is moving: %s', ret, moving)
        return moving

    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees).
        """
        self._logger.debug('Sending move command to mount')
        success = [False]
        def _move_to_alt_az(alt, azi, success):
            #azi = azi %360 #Mount uses 0-360
            # TODO check alt zero correct
            altRaw = int(degrees_to_0_360(alt - self._alt_zero) / 360 * 2**32) & 0xFFFFFF00
            aziRaw = int(degrees_to_0_360(azi) / 360 * 2**32) & 0xFFFFFF00
            altFormatted = '{0:0{1}X}'.format(altRaw,8)
            aziFormatted = '{0:0{1}X}'.format(aziRaw,8)
            command = 'b' + aziFormatted + ',' + altFormatted
            self.send_text_command(command)
            assert self.check_ack(), 'Mount did not acknowledge'
            success[0] = True
        # not sure why the original code used thread to do something not in
        # parallel:
        #t = Thread(target=_move_to_alt_az, args=(alt, azi, success))
        #t.start()
        #t.join()
        _move_to_alt_az(alt, azi, success)
        assert success[0], 'Failed communicating with mount'
        self._logger.debug('Send successful')

    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        ret = [None, None]

        def _get_alt_az(ret):
            command = bytes([ord('z')]) #Get precise AZM-ALT
            self._serial_port.write(command)
            # The command returns ASCII encoded text of HEX values!
            res = self._serial_read_to_eol().decode('ASCII')
            r2 = res.split(',')
            ret[0] = int(r2[1], 16)
            ret[1] = int(r2[0], 16)
        ret = [None, None]
        # not sure why the original code used thread to do something not in
        # parallel:
        #t = Thread(target=_get_alt_az, args=(ret,))
        #t.start()
        #t.join()
        _get_alt_az(ret)

        alt = degrees_to_n180_180( float(ret[0]) / 2**32 * 360 + self._alt_zero)
        azi = degrees_to_n180_180( float(ret[1]) / 2**32 * 360 )
        self._logger.debug('Mount position: alt=%s azi=%s => alt=%s azi=%s',
                           ret[0], ret[1], alt, azi)
        return alt, azi

    def _command_set_axis_rates(self, alt, azi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        self._logger.debug('Using celestron, sending rate command to mount')
        self.clear_buffers()
        success = [False]
        def _set_rate_alt_az(alt, azi, success):
            #Altitude
            rate = int(round(alt*3600*4))
            if rate >= 0:
                rateLo = rate & 0xFF
                rateHi = rate>>8 & 0xFF
                command_bytes = [ord('P'),3,17,6,rateHi,rateLo,0,0]
            else:
                rateLo = -rate & 0xFF
                rateHi = -rate>>8 & 0xFF
                command_bytes = [ord('P'),3,17,7,rateHi,rateLo,0,0]
            self.send_bytes_command(command_bytes)
            self._logger.debug('Sending: '+str(command_bytes))
            assert self.check_ack(), 'Mount did not acknowledge!'
            #Azimuth
            rate = int(round(azi*3600*4))
            if rate >= 0:
                rateLo = rate & 0xFF
                rateHi = rate>>8 & 0xFF
                self.send_bytes_command([ord('P'),3,16,6,rateHi,rateLo,0,0])
            else:
                rateLo = -rate & 0xFF
                rateHi = -rate>>8 & 0xFF
                self.send_bytes_command([ord('P'),3,16,7,rateHi,rateLo,0,0])
            assert self.check_ack(), 'Mount did not acknowledge!'
            success[0] = True

        # not sure why the original code used thread to do something not in
        # parallel:
        #t = Thread(target=_set_rate_alt_az, args=(alt, azi, success))
        #t.start()
        #t.join()
        _set_rate_alt_az(alt, azi, success)

        assert success[0], 'Failed communicating with mount'
        self._logger.debug('Send successful')
        return alt, azi
