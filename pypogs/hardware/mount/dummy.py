"""
Dummy implementation of a mount.

This allows instantiation, but certainly doesn't impact any hardware.
"""

import time, threading

from . import base

class Mount(base.Mount):
    hardware_max_rates = None, None
    hardware_altitude_limits = None, None
    hardware_azimuth_limits = None, None
    _dt = 0.1

    def __init__(self, *a, **kw):
        self._tracking_mode = 'idle'
        self._azimuth = 0.0
        self._altitude = 0.0
        self._moving_thread = None
        self._moving_thread_stop = True
        self._lock = threading.RLock()
        super().__init__(*a, **kw)

    def set_identity(self, identity):
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
        with self._lock:
            return self._tracking_mode

    @tracking_mode.setter
    def tracking_mode(self, value):
        assert value in self.known_tracking_modes, \
          f'Unknown tracking mode: "{value}"'
        with self._lock:
            self._tracking_mode = value

    def _initialize(self):
        pass

    def _deinitialize(self):
        pass

    def _movement_active(self):
        return False

    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees).
        """
        with self._lock:
            self._altitude = alt
            self._azimuth = azi

    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        with self._lock:
            return self._altitude, self._azimuth

    def _command_set_axis_rates(self, alt, azi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        def move_dummy():
            self._moving_thread_stop = False
            while not self._moving_thread_stop:
                with self._lock:
                    self._altitude += alt * self._dt
                    self._azimuth  += azi * self._dt
                time.sleep(self._dt)

        if self._moving_thread:
          self._moving_thread_stop = True
          self._moving_thread.join()
          self._moving_thread = None

        if alt or azi:
            self._moving_thread = threading.Thread(target=move_dummy)
            self._moving_thread.start()

        return alt, azi
