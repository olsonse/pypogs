"""
Implementation of a mount with an ASCOM interface.
"""

from . import base

class Mount(base.Mount):
    # FIXME:  look these up?  Can these be queried?
    _hardware_max_rates = None, None
    hardware_altitude_limits = None, None
    hardware_azimuth_limits = None, None
    _known_tracking_modes = {'sidereal', 'idle'}
    available_properties = base.Mount.available_properties + ('axis_direction',)

    def __init__(self, *a, **kw):
        self._ascom_telescope = None
        self._ascom_scope_alt_axis = 1
        self._ascom_scope_azi_axis = 0
        self._ascom_availableRatesAlt = [0]
        self._ascom_availableRatesAzi = [0]
        self._ascom_driver_handler = None
        #set to 1 to use mount default axis direction, -1 to invert direction
        self.axis_directions = 1, 1

        super().__init__(self, *a, **kw)

    @property
    def hardware_max_rates(self):
        return self._hardware_max_rates

    @property
    def axis_directions(self):
        """tuple of float: Get or set the azimuth limits (degrees) where the mount can safely move.
            May be set to None. Default (None, None). Not enforced when slewing (set_rate) the mount.
        """
        return self._axis_directions
    @axis_directions.setter
    def axis_directions(self, axis_dirs):
        if axis_dirs is None:
            self._logger.debug('Setting axis directions to 1')
            self._axis_directions = (1, 1)
        assert isinstance(axis_dirs, (tuple, list)) and len(axis_dirs)==2, 'Must be 2-tuple'
        assert axis_dirs[0] in [-1, 1] and axis_dirs[1] in [-1, 1], 'Axis directions must be 1 or -1'
        self._logger.debug('Got set axis directions with: '+str(axis_dirs))
        self._axis_directions = (int(axis_dirs[0]) if axis_dirs[0] is not None else None \
                               , int(axis_dirs[1]) if axis_dirs[1] is not None else None)
        self._logger.debug('Set axis directions to: '+str(self._axis_directions))

    def prep_thread(self):
        import pythoncom
        pythoncom.CoInitialize()

    def unprep_thread(self):
        import pythoncom
        pythoncom.CoUninitialize()

    def set_identity(self, identity):
        self._logger.debug('Attempting to connect to ASCOM device "%s"',
                           identity)
        if self._ascom_driver_handler is None:
            self._logger.debug('Loading ASCOM win32com device handler')
            import win32com.client
            self._ascom_driver_handler = win32com.client
        ascomDriverName = str()
        if identity is not None:
            self._logger.debug('Specified identity: "%s" [%d]',
                               identity, len(identity))
            if identity.startswith('ASCOM'):
                ascomDriverName = identity
            else:
                ascomDriverName = f'ASCOM.{identity}.Telescope'
        else:
            ascomSelector = self._ascom_driver_handler.Dispatch("ASCOM.Utilities.Chooser")
            ascomSelector.DeviceType = 'Telescope'
            ascomDriverName = ascomSelector.Choose('None')
            self._logger.info('Selected telescope driver: %s', ascomDriverName)
            if not ascomDriverName:
                self._logger.debug('User canceled telescope selection')
                return False
            try:
                identity = ascomDriverName.replace('ASCOM.','').replace('.Telescope','')
            except:
                identity = None
        if not ascomDriverName:
            raise AssertionError('Failed to identify ASCOM telescope')
        #try:
        self._ascom_telescope = self._ascom_driver_handler.Dispatch(ascomDriverName)
        # FIXME:  why do we set this None right now?!?
        self._ascom_telescope = None
        #except:
        #    raise AssertionError('Failed to connect to ASCOM telescope: '+str(ascomDriverName))
        self._identity = identity

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
        return 'sidereal' if (self._ascom_telescope != None and
                              self._ascom_telescope.Tracking) else 'idle'
    @tracking_mode.setter
    def tracking_mode(self, value):
        if value == 'sidereal':
            if hasattr(self._ascom_telescope, 'CanSetTracking') \
               and self._ascom_telescope.CanSetTracking:
                try:
                    self._ascom_telescope.Tracking = True  #turn on tracking
                except:
                    self._logger.warning('Failed to start sidereal tracking.')
        elif value == 'idle':
            if hasattr(self._ascom_telescope, 'CanSetTracking') \
               and self._ascom_telescope.CanSetTracking:
                try:
                    self._ascom_telescope.Tracking = False  #turn off tracking
                except:
                    self._logger.warning('Failed to stop sidereal tracking.')
        else:
            raise ValueError(f'Do not know how to set tracking_mode="{value}"')

    def _initialize(self):
        """Initialise (make ready to start) the device. The model and identity
        must be defined.
        """
        if self._ascom_telescope is not None:
            raise RuntimeError('ASCOM telescope already exists!')

        self._logger.debug('Attempting to connect to ASCOM device "%s"',
                           self.identity)

        if self._ascom_driver_handler is None:
            import win32com.client
            self._ascom_driver_handler = win32com.client
        if self.identity is not None:
            self._logger.debug('Specified identity: "%s" [%d]',
                               self.identity, len(self.identity))
            if self.identity.startswith('ASCOM'):
                ascomDriverName = self.identity
            else:
                ascomDriverName = f'ASCOM.{self.identity}.Telescope'
        else:
            ascomSelector = \
              self._ascom_driver_handler.Dispatch("ASCOM.Utilities.Chooser")
            ascomSelector.DeviceType = 'Telescope'
            ascomDriverName = ascomSelector.Choose('None')
            self._logger.info("Selected telescope driver: %s", ascomDriverName)
            if not ascomDriverName:
                self._logger.debug('User canceled telescope selection')
                return False

        self._identity = ascomDriverName.replace('ASCOM.','') \
                       .replace('.Telescope','')
        assert ascomDriverName, 'Unable to identify ASCOM telescope.'

        assert self._ascom_driver_handler is not None, \
          'Unable to access win32com driver handler'
        self._logger.info('Loading ASCOM telescope driver: %s', ascomDriverName)
        self._ascom_telescope = \
          self._ascom_driver_handler.Dispatch(ascomDriverName)
        assert self._ascom_telescope is not None, \
          'Failed to intialize ASCOM telescope'
        assert hasattr(self._ascom_telescope, 'Connected'), \
          "Unable to access telescope driver"

        self._logger.debug('Connecting to telescope')
        self._ascom_telescope.Connected = True
        assert self._ascom_telescope.Connected, "Failed to connect to telescope"
        self._logger.debug('Connected to ASCOM telescope')

        if hasattr(self._ascom_telescope, 'CanSetTracking') \
           and self._ascom_telescope.CanSetTracking:
            self._ascom_telescope.Tracking = False  #turn off tracking
        try:
            self._ascom_canSlewAltAz = self._ascom_telescope.CanSlewAltAz
        except:
            self._ascom_canSlewAltAz = False

        max_speed = [0, 0]
        for axis in [0, 1]:
            self._logger.debug('axis "%s", rate count: "%s"', axis,
                               self._ascom_telescope.AxisRates(axis).Count)
            for i in range(1, self._ascom_telescope.AxisRates(axis).Count+1):
                self._logger.debug('axis rate {}, min: {}, max: {}', i,
                  self._ascom_telescope.AxisRates(axis).Item(i).Minimum,
                  self._ascom_telescope.AxisRates(axis).Item(i).Maximum)

            max_speed[axis] = self._ascom_telescope.AxisRates(axis).Item(i).Maximum

        for i in range(1, self._ascom_telescope.AxisRates(self._ascom_scope_alt_axis).Count+1):
            self._ascom_availableRatesAlt.append(
              float(self._ascom_telescope.AxisRates(self._ascom_scope_alt_axis).Item(i).Maximum))

        for i in range(1, self._ascom_telescope.AxisRates(self._ascom_scope_azi_axis).Count+1):
            self._ascom_availableRatesAzi.append(
              float(self._ascom_telescope.AxisRates(self._ascom_scope_azi_axis).Item(i).Maximum))

        # absolute hardware max rates must be set before user-defined rates
        self._hardware_max_rates = (max_speed[self._ascom_scope_alt_axis],
                                    max_speed[self._ascom_scope_azi_axis])
        self.max_rate = self.hardware_max_rates

    def _deinitialize(self):
        self._logger.debug('Disconnecting ASCOM telescope mount')
        if self._ascom_telescope is not None:
            try:
                if self._ascom_telescope.Connected:
                    self._ascom_telescope.AbortSlew()
                self._ascom_telescope.Connected = False
            except:
                pass
        import pythoncom
        pythoncom.CoUninitialize()
        self._ascom_telescope = None

    def _movement_active(self):
        """
        Returns True if the mount can natively report that it has active motion.

        Generally should only be called by self.is_moving.
        """
        return self._ascom_telescope.Slewing or self._ascom_telescope.Tracking

    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees).
        """
        if not self._ascom_telescope.CanSlewAltAz:
            raise RuntimeError('ASCOM mount does not support alt/az go-to commanding')
        if self._ascom_telescope.AtPark:
            raise RuntimeError('ASCOM mount is parked; cannot command alt/az slew')
        if self._ascom_telescope.Tracking:
            raise RuntimeError('ASCOM mount is tracking; cannot command alt/az slew')
        self._ascom_telescope.SlewToAltAz(alt, azi)

    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        alt = self._ascom_telescope.Altitude
        azi = self._ascom_telescope.Azimuth
        self._logger.debug('Mount position: alt=%s azi=%s', alt, azi)
        return alt, azi

    def _command_set_axis_rates(self, alt, azi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        if abs(alt) > self.hardware_max_rates[0]:
            sign = 1 if alt >= 0 else -1
            alt = sign * self.hardware_max_rate[0]
        if abs(azi) > self.hardware_max_rates[1]:
            sign = 1 if azi >= 0 else -1
            azi = sign * self.hardware_max_rate[1]

        if alt==0 and azi==0:
            try:
                self._ascom_telescope.AbortSlew()
            except:
                pass

        rates = list(self._axis_directions)
        rates[self._ascom_scope_alt_axis] *= alt
        rates[self._ascom_scope_azi_axis] *= azi

        self._logger.debug('Commanding alt rate: %s',
                           rates[self._ascom_scope_alt_axis])
        self._ascom_telescope.MoveAxis(self._ascom_scope_alt_axis,
                                       rates[self._ascom_scope_alt_axis])

        self._logger.debug('Commanding azi rate: %s',
                           rates[self._ascom_scope_azi_axis])
        self._ascom_telescope.MoveAxis(self._ascom_scope_azi_axis,
                                       rates[self._ascom_scope_azi_axis])
        # Not sending the data from 'rates' since it seems that the axis
        # direction should be hidden from the calculations in pypogs and only
        # internal to this ascom driver
        return alt, azi
