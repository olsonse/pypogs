"""
Implementation of a iOptron AZ mount.
"""

from . import serial

class AZMP(serial.Mount):
    baud = 115200
    port_test = dict(
      command=':MountInfo#',
      response_regex = b'(5035|9035)$',
    )
    _known_tracking_modes = {'sidereal', 'idle'}

    # FIXME:  look these up?  Can these be queried?
    hardware_max_rates = None, None
    hardware_altitude_limits = None, None
    hardware_azimuth_limits = None, None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)

        self._azmp_command_modes = {b'5035': 'normal', b'9035': 'special'}
        self._azmp_states = {
            '0': 'stopped at non-zero pos',
            '1': 'tracking with PEC disabled',
            '2': 'slewing',
            '3': 'autoguiding',
            '4': 'meridian flipping',
            '5': 'tracking with PEC enabled',
            '6': 'parked',
            '7': 'stopped at zero pos'
        }
        self._azmp_command_mode_names = self._azmp_command_modes.values()
        self._azmp_command_mode_code = b''

    def move_to_alt_az(self, alt, azi, block=True, rate_control=True,
                       tolerance_deg=0.001, min_speed=0.001):

        self.azmp_set_command_mode('special')
        return super().move_to_alt_az(alt, azi, block, rate_control,
                                      tolerance_deg, min_speed)

    @property
    def tracking_mode(self):
        """
        Return the current tracking mode of the mount.  This return value should
        generally be taken from one of the following:
          - sidereal
          - solar
          - lunar
          - custom
          - idle (for "not tracking", or simple "GoTo")
        """
        # Sidereal tracking (and state query) is only available in normal
        # commanding mode.
        if self._azmp_command_mode == 'normal':
            mount_state = self.query_command(':GLS#').decode('ASCII')
            # The 18th digit indicates system status:
            # 1 = tracking with PEC disabled,
            # 5 = tracking with PEC enabled
            status = mount_state[14]
            self._logger.debug('Mount tracking state: "%s"', status)
            return 'sidereal' if status in '15' else 'idle'
        return 'idle'

    @tracking_mode.setter
    def tracking_mode(self, value):
        if value == 'sidereal':
            # sidereal tracking (and state check) is only supported in normal
            # commanding mode.
            self.azmp_set_command_mode('normal')
            assert self._azmp_command_mode == 'normal', \
              'Cannot enable sidereal tracking in "%s" mode' \
              % self._azmp_command_mode
            assert self.query_command(':ST1#', b'1') is not None, \
              'Mount did not acknowledge!'
            #self.send_text_command(':ST1#')
            #assert self.check_ack('1'), 'Mount did not acknowledge!'
        elif value == 'idle':
            # sidereal tracking (and state check) is only supported in normal
            # commanding mode.
            #self.azmp_get_command_mode()
            if self._azmp_command_mode == 'normal':
                #self.send_text_command(':ST0#')
                #assert self.check_ack('1'), \
                #  'Mount did not acknowledge!'
                assert self.query_command(':ST0#', b'1') is not None, \
                  'Mount did not acknowledge!'
                #self.azmp_set_command_mode('special')
                #assert self._azmp_command_mode == 'special', \
                #  'Unable to switch mount to special command mode.'
                #self.get_alt_az()
        else:
            raise ValueError(f'Do not know how to set tracking_mode="{value}"')

    def azmp_get_command_mode(self):
        """Get the iOptron AZMP command mode. Returns either 'normal' or
        'special'
        """
        self._logger.debug('Checking AZMP command mode')
        assert self._serial_is_init, 'Serial port is not initialized'
        self.clear_buffers()
        self.send_text_command(':MountInfo#')
        command_mode_code = self._serial_port.read(4)
        assert command_mode_code in (b'5035', b'9035'), \
          f'Failed to get AZMP command mode. Mount gave: {command_mode_code}'
        self._azmp_command_mode = \
          'normal' if command_mode_code == b'5035' else 'special'
        self._logger.info('AZMP command mode is "%s" (%s)',
                          self._azmp_command_mode, command_mode_code)

    def azmp_set_command_mode(self, to_mode):
        self._logger.debug('Got request to transition mount to %s command mode',
                           to_mode)
        self.azmp_get_command_mode()
        if self._azmp_command_mode == to_mode:
            self._logger.debug('Mount is already in command mode "%s"',
                               self._azmp_command_mode)
        else:
            self._logger.debug('Commanding AZMP mode transition')
            self.send_text_command(':ZZZ#')
            sleep(2.5)
            self.azmp_get_command_mode()
            assert self._azmp_command_mode == to_mode, \
              f'Failed to transition mount to {to_mode} commanding mode"'

    def _initialize(self):
        """Initialise (make ready to start) the device. The model and identity
        must be defined.
        """
        assert not self.serial_is_open, 'Serial port already open'
        assert self.identity is not None, 'Define identity before initialising'
        self._logger.debug('Using %s, try to initialise', self.model)
        self._logger.debug('Opening serial port "%s"', self.identity)
        self.open()
        self._logger.debug('Opened serial port, checking command mode')
        # Command mode persists across resets. Expect either mode initially, and
        # try to get to special mode.
        self.azmp_get_command_mode()
        assert self._azmp_command_mode in self._azmp_command_mode_names, \
          'Failed to get initial mount commanding mode.'
        self._logger.debug('Initial command mode: %s', self._azmp_command_mode)
        if self._azmp_command_mode == 'normal':
            self._logger.debug('Ensuring sidereal tracking is off and '
                               'transition to special')
            self.stop_sidereal_tracking()
            self.azmp_set_command_mode('special')
            assert self._azmp_command_mode == 'special', \
              'Unable to switch mount to special command mode.'

    def _deinitialize(self):
        self._logger.debug('Using iOptron AZMP, reverting mount commanding mode to normal')
        self._azmp_set_command_mode('normal')
        super()._deinitialize()

    def _movement_active(self):
        """
        Returns True if the mount can natively report that it has active motion.

        Generally should only be called by self.is_moving.
        """
        is_moving = False
        self._logger.debug('Using %s in %s command mode, asking if moving',
                           self.model, self._azmp_command_mode)
        if self._azmp_command_mode == 'special':
            azi_axis_rate = self.query_command(':Q0#').decode('ASCII')
            alt_axis_rate = self.query_command(':Q1#').decode('ASCII')
            self._logger.debug('azi_axis_rate: "%s", alt_axis_rate: "%s"',
                               azi_axis_rate, alt_axis_rate)
            try:
                is_moving = (int(azi_axis_rate or 0) != 0 or
                             int(alt_axis_rate or 0) != 0)
            except:
                raise AssertionError('invalid rate query response ('
                  f'azi_axis_rate: "{azi_axis_rate}", '
                  f'alt_axis_rate: "{alt_axis_rate}")')
        else:
            mount_system_status_char = ''
            mount_state = self.query_command(':GLS#')
            self._logger.debug('iOptron mount state: %s', mount_state)
            assert mount_state is not None and len(mount_state)>14, \
              f'Unexpected AZMP state query response: "{mount_state}"'

            try:
                mount_system_status_char = mount_state.decode('ASCII')[14]
                self._logger.debug('iOptron mount state status char: %s',
                                   mount_system_status_char)
                mount_system_state = self._azmp_states[mount_system_status_char]
                self._logger.debug('AZMP system state: "%s" (%s)',
                                   mount_system_state, mount_system_status_char)
            except KeyError:
                self._logger.warning(
                  'Unexpected AZMP state query response: "%s", status byte: %s',
                  mount_state, mount_state.decode[14])
            assert mount_system_status_char in self._azmp_states, \
              f'Invalid AZMP state index: {mount_system_status_char}'

            # azmp motion states are between 1 and 5 inclusive
            is_moving = mount_system_status_char in '12345'
        return is_moving

    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees).
        """
        # TODO check alt zero correct
        self._azmp_set_command_mode('special')
        # Azimuth:
        command = 'T0%+i#' % int(degrees_to_0_360(azi) * 3600 / 0.01)
        self.send_text_command(command)
        # Altitude:
        command = 'T1%+i#' % int(degrees_to_0_360(alt - self._alt_zero) * 3600 / 0.01)
        self.send_text_command(command)

    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        (alt, azi) = (None, None)
        if self._azmp_command_mode == 'special':
            # returns integer units of 0.01 arcsec
            for attempt in (0, 1):
                azi_raw = self.query_command(':P0#').decode('ASCII')
                alt_raw = self.query_command(':P1#').decode('ASCII')
                try:
                    azi = degrees_to_n180_180( int(azi_raw) * 0.01 / 3600 + 180 )
                    alt = degrees_to_n180_180( 90 - int(alt_raw) * 0.01 / 3600 + self._alt_zero)
                    break
                except:
                    self._logger.info('WARNING: invalid responses from mount '
                                      '(alt: "%s", azi: "%s")', alt_raw,azi_raw)
        elif self._azmp_command_mode == 'normal':
            # returns char array: : “sTTTTTTTTTTTTTTTTT#”
            mount_altaz_info = self.query_command(':GAC#').decode('ASCII')
            assert mount_altaz_info is not None, 'Failed to get mount position.'
            alt_raw = int(mount_altaz_info[0:9])
            azi_raw = int(mount_altaz_info[9:18])
            azi = degrees_to_n180_180( int(azi_raw) * 0.01 / 3600 )
            alt = degrees_to_n180_180( int(alt_raw) * 0.01 / 3600 + self._alt_zero)

        self._logger.debug('Mount position: alt=%s azi=%s  => alt=%s azi=%s',
                           alt_raw, azi_raw, alt, azi)
        return alt, azi

    def _command_set_axis_rates(self, alt, azi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        #self._logger.debug('Using %s, sending rate command to mount' % self.model)
        self.clear_buffers()
        if self._azmp_command_mode == 'special':
            # convert rates to integer units of 0.01 arcsec/second
            alt_rate_command = ':M1%+i#' % int(round(-1*alt*3600/0.01))
            azi_rate_command = ':M0%+i#' % int(round(azi*3600/0.01))
            self.query_command(alt_rate_command, eol_byte = b'1')
            self.query_command(azi_rate_command, eol_byte = b'1')
        elif self._azmp_command_mode == 'normal' and alt==0 and azi==0:
            # support zero-rate commanding in normal mode specifically to support the stop method.
            self.query_command(':Q#', eol_byte = b'1')  # "quit slew" command stops
        else:
            raise AssertionError('Non-zero rate requested while mount is not in compatible mode.')

        self._logger.debug('Send successful')
        return alt, azi
