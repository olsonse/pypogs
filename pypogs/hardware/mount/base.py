# vim: ts=4:sw=4:tw=80:nowrap

import abc, logging, time
from pathlib import Path
from threading import Thread, RLock
from math import copysign

from .. import base
from .. import factory as factory_module
from .util import *

class Mount(base.Hardware):
    """Pypogs interface to control a telescope gimbal mount.

    To intantiate a Mount, the *model* (determines hardware interface) must be
    given to the Mount.factory.  To initialise a Mount, an *identity*
    (identifying the specific device) must be specified. If the identity is
    given to the constructor, the Mount will be initialised immediately (unless
    auto_init=False is passed). Manually initialise with a call to
    Mount.initialize(); release hardware with a call to Mount.deinitialize().

    After the Mount is initialised, the gimbal angles and rates may be read and
    commanded. Several properties (e.g maximum angles and rates) may be set.

    Args:
        identity (str or int, optional): String or int identifying the device.
            For model *Celestron* this can either be a string with the serial
            port (e.g.  'COM3' on Windows or '/dev/ttyUSB0' on Linux) or an int
            with the index in the list of available ports to use (e.g.
            identity=0 i if only one serial device is connected.)
            For model *ASCOM* this can either be left blank to invoke the ASCOM
            telescope selection menu, or may specify a specific installed ASCOM
            driver by (case sensitive) name (e.g. DeviceHub, Celestron,
            Simulator, SkyWatcher, etc).
        name (str, optional): Name for the device.
        auto_init (bool, optional): If both model and identity are given when
            creating the Mount and auto_init is True (the default),
            Mount.initialize() will be called after creation.
        debug_folder (pathlib.Path, optional): The folder for debug logging. If
            None (the default), the folder *pypogs*/logs will be used/created.

    Example:
        ::

            # Create instance (will auto initialise)
            mount = pypogs.Mount.factory('Celestron').(identity='COM3', name='CPC800')
            # Move to position
            mount.move_to_alt_az(30, 10) #degrees; by default blocks until finished
            # Set gimbal rates
            mount.set_rate_alt_az(0, -1.5) #degrees per second
            # Wait for a while
            time.sleep(2)
            # Stop moving
            mount.stop()
            # Disconnect from the mount
            mount.deinitialize()

    Notes:
        1) The Mount class allows two modes of control for moving to positions.
           The default is rate_control=True, where this class will continuously
           send rate commands until the desired position is reached. It is
           possible to use the internal motion controller in the mount by
           passing rate_control=False.  However, it is slow and implements
           backlash compensation. In our testing the accuracy difference is
           negligible so the default is recommended.

        2) The :class:`pypogs.Mount` class is actually an abstract class and
           cannot be directly instantiated.  As described above,
           :class:`pypogs.Mount` implementations that can be instantiated should
           generally be looked up using the :function:`pypogs.Mount.factory`
           static function.
    """
    # Notes to developers:
    # For several of the abstract functions below, it is left to the
    # implementing child class to handle things like *not* making a change
    # when it is superfluous.

    type = 'mount'

    #
    # Set of all available properties for this device.
    # Child classes can add to this, override this with a class value, or with a
    # @property.
    available_properties = (
      'zero_altitude', 'home_alt_az', 'max_rate', 'alt_limit', 'azi_limit',
    ) + base.Hardware.available_properties

    # mounts should probably override this, but should include (and implement)
    # 'sidereal' and 'custom' to work for pypogs
    known_tracking_modes = {'sidereal', 'solar', 'lunar', 'custom', 'idle'}

    EMPTY_STATE_CACHE = {'alt' : None, 'azi' : None,
                         'alt_rate' : None, 'azi_rate' : None}

    def __init__(self, *a, **kw):
        """
        Abstract base class for all mounts.  Some mount properties can be
        defined by keyword arguments to the mount constructor.
        """
        self._max_speed = (4.0, 4.0) #(alt,azi) degrees/sec
        self._alt_limit = (-5, 95) #limit degrees
        self._azi_limit = (None, None) #limit degees
        self._home_pos = (0, 0) #Home position
        self._alt_zero = 0 #Amount to subtract from alt.
        # Thread for rate control
        self._control_thread = None
        self._control_thread_stop = True
        # Cache of the state of the mount
        self._state_cache = self.EMPTY_STATE_CACHE.copy()
        self.lock = RLock()
        super().__init__(*a, **kw)

    @property
    def state_cache(self):
        """dict: Get cache with the current state of the Mount. Updates on calls
        to get_alt_az() and set_rate_alt_az().

        Keys:
            azi: float, alt: float, azi_rate: float, alt_rate: float

        Returns a *copy* of the current state cache.
        """
        if self.is_init:
            with self.lock:
                return self._state_cache.copy()
        else:
            return self.EMPTY_STATE_CACHE.copy()

    @property
    def zero_altitude(self):
        """float: Get or set the zero altitude angle (degrees). Default 0.

        Normally the mount is initialised with the telescope level. In this case
        zero_altitude is 0. However, if the mount is e.g. initialised with the
        telescope pointing straight up, zero_altitude must be set to +90.
        """
        return self._alt_zero
    @zero_altitude.setter
    def zero_altitude(self, angle):
        self._logger.debug('Got set zero altitude with: '+str(angle))
        self._alt_zero = float(angle)
        self._logger.debug('Alt zero set to: '+str(self._alt_zero))

    @property
    def home_alt_az(self):
        """
        tuple of float: Get or set the home position (altitude, azimuth) in
        degrees. Default (0, 0)
        """
        return self._home_pos
    @home_alt_az.setter
    def home_alt_az(self, pos):
        self._logger.debug('Got set home pos with: '+str(pos))
        assert pos in (int, float) or len(pos) == 2, 'Must be scalar or array of length 2'
        if pos in (int, float):
            pos = tuple([float(x) for x in pos])
        else:
            pos = (float(pos), float(pos))
        self._home_pos = pos
        self._logger.debug('Home pos set to: '+str(self.home_alt_az))

    @property
    def max_rate(self):
        """tuple of float: Get or set the max slew rate (degrees per second) for
        the axes (altitude, azimith).
        Default (4.0, 4.0).

        If a scalar is set, both axes' rates will be set to this value.
        """
        return self._max_speed
    @max_rate.setter
    def max_rate(self, maxrate):
        self._logger.debug('Requested to set max rate to %s', maxrate)
        assert isinstance(maxrate, (int, float)) or len(maxrate) == 2, \
          'Must be scalar or array of length 2'
        if isinstance(maxrate, (int, float)):
            maxrate = [float(maxrate), float(maxrate)]
        else:
            maxrate = [float(maxrate[0]), float(maxrate[1])]

        # now limit user-inputs to any given hardware-provided absolute maxima
        hw = self.hardware_max_rates
        if hw[0] is not None:
          maxrate[0] = min(maxrate[0], hw[0])
        if hw[1] is not None:
          maxrate[1] = min(maxrate[1], hw[1])

        self._max_speed = tuple(maxrate)
        self._logger.debug('Set max rate to: %s', self.max_rate)


    @abc.abstractproperty
    def hardware_max_rates(self):
        """
        Tuple of limiting axis rates as (altitude, azimuth) as defind by the
        hardware.  Return (None, None) if there are no known limits.

        Used to limit what rate can be set by the user.
        """
        pass

    @property
    def alt_limit(self):
        """
        tuple of float: Get or set the altitude limits (degrees) where the mount
        can safely move.  May be set to None. Default (-5, 95). Not enforced
        when slewing (set_rate) the mount.
        """
        return self._alt_limit
    @alt_limit.setter
    def alt_limit(self, altlim):
        if altlim is None:
            self._logger.debug('Setting alt limit to None')
            self._alt_limit = (None, None)
        else:
            assert isinstance(altlim, (tuple, list)) and len(altlim)==2, 'Must be 2-tuple'
            self._logger.debug('Got set alt limits with: '+str(altlim))
            self._alt_limit = (
              float(altlim[0]) if altlim[0] is not None else None,
              float(altlim[1]) if altlim[1] is not None else None,
            )
        self._logger.debug('Set alt limit to: '+str(self._alt_limit))

    @property
    def azi_limit(self):
        """tuple of float: Get or set the azimuth limits (degrees) where the mount can safely move.
            May be set to None. Default (None, None). Not enforced when slewing (set_rate) the mount.
        """
        return self._azi_limit
    @azi_limit.setter
    def azi_limit(self, azilim):
        if azilim is None:
            self._logger.debug('Setting azi limit to None')
            self._azi_limit = (None, None)
        assert isinstance(azilim, (tuple, list)) and len(azilim)==2, 'Must be 2-tuple'
        self._logger.debug('Got set azi limits with: '+str(azilim))
        self._azi_limit = (float(azilim[0]) if azilim[0] is not None else None \
                           , float(azilim[1]) if azilim[1] is not None else None)
        self._logger.debug('Set azi limit to: '+str(self._azi_limit))

    @abc.abstractproperty
    def hardware_altitude_limits(self):
        """
        Hard limits on altitude (from the hardware).
        Return (None, None) if there are no known limits.
        """
        pass

    @abc.abstractproperty
    def hardware_azimuth_limits(self):
        """
        Hard limits on altitude (from the hardware).
        Return (None, None) if there are no known limits.
        """
        pass

    @property
    def is_sidereal_tracking(self):
        return self.tracking_mode == 'sidereal'

    @property
    def is_custom_tracking(self):
        return self.tracking_mode == 'custom'

    @abc.abstractproperty
    def tracking_mode(self):
        """
        Return the current tracking mode of the mount.  This return value should
        generally be taken from one of the following:
          - sidereal (*required)
          - solar
          - lunar
          - custom (can accept custom rates for axis motion; *required)
          - idle (for "not tracking", or simple "GoTo")

        Implementing classes should also implement this as a setter.
        """
        pass

    @property
    def is_moving(self):
        """Returns True if the mount is currently moving."""
        assert self.is_init, 'Must be initialised'
        self._logger.debug('Got is moving request, checking thread')
        if self._control_thread is not None and self._control_thread.is_alive():
            self._logger.debug('Has active control thread')
            return True

        # resort to relying on mount reporting whether it has active motion
        return self._movement_active()

    @abc.abstractproperty
    def _movement_active(self):
        """
        Returns True if the mount can natively report that it has active motion.

        Generally should only be called by self.is_moving.
        """
        pass

    def move_to_alt_az(self, alt, azi, block=True, rate_control=True,
                       tolerance_deg=0.001, min_speed=0.001):
        """Move the mount to the given position. Must be initialised.

        Args:
            alt (float): Altitude angle (degrees).
            azi (float): Azimuth angle (degrees).
            block (bool, optional): If True (the default) the call to this
                method will block until the move is finished.
            rate_control (bool, optional): If True (the default) the rate of the
                mount will be controlled until position is reached, if False the
                position command will be sent to the mount for execution.
        """
        assert self.is_init, 'Must be initialised'
        assert self._alt_limit[0] is None or alt >= self._alt_limit[0], 'Altitude outside range!'
        assert self._alt_limit[1] is None or alt <= self._alt_limit[1], 'Altitude outside range!'
        assert self._azi_limit[0] is None or azi >= self._azi_limit[0], 'Azimuth outside range!'
        assert self._azi_limit[1] is None or azi <= self._azi_limit[1], 'Azimuth outside range!'
        self._logger.debug(
          'Got move command with: alt=%g azi=%g block=%s rate_control=%s',
          alt, azi, bool(block), bool(rate_control))
        self._logger.debug('Stopping mount first')
        self.stop()

        self._logger.debug('Adjusting range to -180 to 180')
        alt = degrees_to_n180_180(alt - self._alt_zero)
        alt = degrees_to_n180_180(alt)
        azi = degrees_to_n180_180(azi)
        self._logger.debug('Will command to alt=%g azi=%g', alt, azi)

        if not rate_control: # Command mount natively
            self._logger.debug('Sending move command to mount')
            success = [False]
            def _move_to_alt_az(alt, azi, success):
                success[0] = _command_to_alt_az(alt, azi)
            # not sure why we were using a thread to do something serially
            #t = Thread(target=_move_to_alt_az, args=(alt, azi, success))
            #t.start()
            #t.join()
            _move_to_alt_az(alt, azi, success)
            self._logger.debug('Send successful')
            if block:
                self._logger.debug('Waiting for mount to finish')
                self.wait_for_move_to()

        else: # Use own control thread
            self._logger.debug('Starting rate controller')
            Kp = 0.8
            self._control_thread_stop = False
            success = [False]
            def _loop_slew_to(alt, azi, success):
                self.prep_thread();
                while not self._control_thread_stop:
                    curr_pos = self.get_alt_az()
                    # Get current position error
                    error_alt = degrees_to_n180_180(alt - curr_pos[0])
                    error_azi = degrees_to_n180_180(azi - curr_pos[1])

                    if abs(error_alt) < tolerance_deg:
                        rate_alt = 0
                    else:
                        rate_alt = Kp * error_alt
                        # Clip to maximum and minimum speeds
                        if abs(rate_alt) > self.max_rate[0]:
                            rate_alt = copysign(self.max_rate[0], rate_alt)
                        if abs(rate_alt) < min_speed:
                            rate_alt = copysign(min_speed, rate_alt)

                    if abs(error_azi) < tolerance_deg:
                        rate_azi = 0
                    else:
                        rate_azi = Kp * error_azi
                        # Clip to maximum and minimum speeds
                        if abs(rate_azi) > self.max_rate[1]:
                            rate_azi = copysign(self.max_rate[1], rate_azi)
                        if abs(rate_azi) < min_speed:
                            rate_azi = copysign(min_speed, rate_azi)

                    self.set_rate_alt_az(rate_alt, rate_azi)
                    if rate_alt == 0 and rate_azi == 0:
                        success[0] = True
                        break

                self._control_thread_stop = True
        self._control_thread = Thread(target=_loop_slew_to, args=(alt, azi, success))
        self._control_thread.start()
        if block:
            self._logger.debug('Waiting for thread to finish')
            self._control_thread.join()
            #assert success[0], 'Failed moving with rate controller'

    def _command_to_alt_az(self, alt, azi):
        self._logger.debug('Got request to command to alt: %0.3f, azi: %0.3f',
                           alt, azi)
        assert self.is_init, 'Must be initialised'
        return self._do_command_to_alt_az(alt, azi)

    @abc.abstractmethod
    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees).
        """
        pass

    def get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        assert self.is_init, 'Must be initialised'
        #self._logger.debug('Requesting mount position')
        alt, azi = self._command_get_alt_az()
        with self.lock:
            self._state_cache['alt'] = alt
            self._state_cache['azi'] = azi
        return alt, azi

    def _post_initialize(self):
        """Finish init with getting coords."""
        try:
            self.get_alt_az() #Get cache to update
        except AssertionError:
            self._logger.debug('Failed to set state cache', exc_info=True)

    @abc.abstractmethod
    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        pass

    def move_home(self, block=True, rate_control=True):
        """Move to the position defined by Mount.home_alt_az.

        Args:
            block (bool, optional): If True (the default) the call to this method will block until the move is finished.
            rate_control (bool, optional): If True (the default) the rate of the mount will be controlled until position
                is reached, if False the position command will be sent to the mount for execution.
        """
        self.move_to_alt_az(*self.home_alt_az, block=block, rate_control=rate_control)

    def set_rate_alt_az(self, alt, azi):
        """Set the mount slew rate. Must be initialised.

        Args:
            alt (float): Altitude rate (degrees per second).
            azi (float): Azimuth rate (degrees per second).

        If hardware_max_rates are defined by the mount, these requests will be
        modified by that.
        """
        assert self.is_init, 'Must be initialised'
        self._logger.debug('Got rate command. alt=' + str(alt) + ' azi=' + str(azi))
        if (abs(alt) > self.max_rate[0]):
            raise ValueError('Altitude rate above maximum speed! '
                             f'(|{alt}| > {self.max_rate[0]})')

        if (abs(azi) > self.max_rate[1]):
            raise ValueError('Azimuth rate above maximum speed! '
                             f'(|{azi}| > {self.max_rate[1]})')

        hw = self.hardware_max_rates
        if hw[0] != None and abs(alt) > hw[0]:
            old_alt = alt
            alt = copysign(hw[0], alt)
            self._logger.debug(
              'Limiting requested altitude rate %g by hardware defined max %g',
              old_alt, alt)
        if hw[1] != None and abs(azi) > hw[1]:
            old_azi = azi
            azi = copysign(hw[1], azi)
            self._logger.debug(
              'Limiting requested azimuth rate %g by hardware defined max %g',
              old_azi, azi)

        alt, azi = self._command_set_axis_rates(alt, azi)
        with self.lock:
            self._state_cache['alt_rate'] = alt
            self._state_cache['azi_rate'] = azi

    @abc.abstractmethod
    def _command_set_axis_rates(self, alt, azi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        pass

    def switchto_sidereal_tracking(self):
        """
        Only a backwards compatible helper function to set tracking to sidereal
        """
        self.tracking_mode = 'sidereal'

    def switchto_custom_tracking(self):
        """Helper function to stop all tracking."""
        self.tracking_mode = 'custom'

    def stop(self):
        """
        Stop mount motion.
        """
        self._logger.debug('Got stop command, check thread')
        if self.is_init:
            self._logger.info('stopping mount')
            if self._control_thread is not None and self._control_thread.is_alive():
                self._logger.debug('Stopping control thread')
                self._control_thread_stop = True
                self._control_thread.join()
                self._logger.debug('Stopped')
            self._logger.debug('Sending zero rate command')
            self.set_rate_alt_az(0, 0)
            if not self.is_custom_tracking:
                self.switchto_custom_tracking()
        self._logger.debug('Stopped mount')

    def wait_for_move_to(self, timeout=120):
        """Wait for mount to finish move.

        Args:
            timeout (int, optional): Maximum time (seconds) to wait before
            raising TimeoutError. Default 120.
        """
        assert self.is_init, 'Must be initialised'
        t_start = time.time()
        self._logger.debug('Waiting for move to, start time: %d', t_start)
        try:
            while time.time() - t_start < timeout:
                if self.is_moving:
                    time.sleep(.5)
                else:
                    return
        except KeyboardInterrupt:
            self._logger.debug('Waiting interrupted', exc_info=True)

        raise TimeoutError(f'Waiting for mount move took more than {timeout}s.')
