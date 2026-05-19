# vim: ts=4:sw=4:tw=80:nowrap
"""
INDI implementation of a mount.

This interface allows for more use of INDI-supported hardware, opening up more
generic access to mount hardware.
"""

import time
from functools import cached_property
from math import copysign
from astropy import units as U
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, FK5
from astropy.time import Time
import numpy as np
import PyIndi

from . import base
from .. import indi_base

def INDI_az_to_pypogs_az(azimuth):
    """
    Convert from more conventional azimuth coordinates to what pypogs uses.
    Conventional: 0°(North)->90°(East)->180°(South)->270°(West)
    Pypogs:       -180°(South)->-90°(West)->0°(North)->90°(East)->180°(South)
    """
    return ((azimuth - 180) % 360) - 180

def pypogs_az_to_INDI_az(azimuth):
    """Convert from pypogs azimuth to more conventional azimuth
    See INDI_az_to_pypogs_az.
    """
    return azimuth % 360

# be sure to keep PyIndi.BaseClient as the last in the inheritance chain because
# the PyIndi SWIG implementation does not correctly call super().__init__().
class Mount(base.Mount, indi_base.Hardware):
    """Pypogs interface to an INDI-supported mount.

    Identity is specified as:
      [HOST[:PORT]/]MOUNT

        MOUNT may be quoted for INDI device names including : and / chareacters.

    where
      HOST : hostname of remote INDI server (defaults to localhost).
      PORT : TCP port of remote INDI server (defaults to 7624).
      MOUNT: Name of Telescope interface on remote INDI server.
    """
    _hardware_max_rates = None, None
    hardware_altitude_limits = None, None
    hardware_azimuth_limits = None, None

    available_properties = base.Mount.available_properties + ('location',)

    CACHED_PROPERTIES = indi_base.Hardware.CACHED_PROPERTIES + [
      'known_tracking_modes', 'mount_type', 'has_custom_track_rate',
    ]

    REQUIRED_INTERFACE = PyIndi.BaseDevice.TELESCOPE_INTERFACE

    def __init__(self, *a, **kw):
        # mount location taken from GEOGRAPHIC_COORD property from mount
        self._location = None
        # raw ra/dec given from EQUATORIAL_EOD_COORD property from mount
        self._ra_dec = {'RA':0.0, 'DEC':0.0}
        # number of ra_dec or location updates since last conversion to altaz
        # (helps to recompute altaz if location is updated)
        self._recent_updates = 0
        self._total_updates_handled = 0
        # AltAzimuth converted from ra_dec using mount location + time
        # STORED in INDI(0-360 North-East-Up)
        # *only* updated when self_recent_updates > 0
        self._altaz = [0.0, 0.0]
        super().__init__(*a, **kw)

    def _post_initialize(self):
        """INDI will wait until next property update..."""
        pass

    def _initialize(self):
        super()._initialize()

        # absolute hardware max rates (or at least as represented by INDI)
        tr = self.getProperty('Number', 'TELESCOPE_TRACK_RATE')
        mx = (min(abs(tr[0].getMin()), tr[0].getMax()) * U.arcsec/U.s,
              min(abs(tr[1].getMin()), tr[1].getMax()) * U.arcsec/U.s)
        self._hardware_max_rates = (float(mx[0].to(U.deg/U.s).value),
                                    float(mx[1].to(U.deg/U.s).value))

    @property
    def hardware_max_rates(self):
        return self._hardware_max_rates

    @cached_property
    def known_tracking_modes(self):
        assert self.is_init, 'Cannot query tracking modes without connection'
        K = {sw_i.getLabel().lower()
             for sw_i in self.getProperty('Switch', 'TELESCOPE_TRACK_MODE')}
        K.add('idle')
        return K

    @cached_property
    def mount_type(self):
        assert self.is_init, 'Cannot query tracking modes without connection'
        mt = self.getProperty('Switch', 'TELESCOPE_MOUNT_TYPE')
        S = {mi.getName().lower() for mi in mt if mi.getState() ==PyIndi.ISS_ON}
        assert len(S) == 1, 'INDI Telescope is more than one mount type!!!'
        return S.pop()

    @cached_property
    def has_custom_track_rate(self):
        """
        Boolean of whether this mount can set custom tracking rates:
          1) Does it have a "custom" tracking mode?
          2) Can we successfully send a copy of the current tracking rate?
        """
        # 1) has "custom" tracking mode?
        if not 'custom' in self.known_tracking_modes:
            return False

        # 2) can we send a (copy of the current) tracking rate?
        tr = self.getProperty('Number', 'TELESCOPE_TRACK_RATE')
        self.sendNewNumber(tr)
        tf = time.time() + 4 * self.polling_period # quite permissive in time
        while time.time() <= tf:
            time.sleep(0.1)
            if tr.getState() == PyIndi.IPS_OK:
                return True
        return False

    @property
    def tracking_active(self):
        """The enable tracking switch."""
        sw = self.getProperty('Switch', 'TELESCOPE_TRACK_STATE')
        S = {i.getName().lower():(i.getState()==PyIndi.ISS_ON) for i in sw}
        return S.get('track_on', False)
    @tracking_active.setter
    def tracking_active(self, value):
        new_state = 'track_on' if bool(value) else 'track_off'
        sw = self.getProperty('Switch', 'TELESCOPE_TRACK_STATE')
        sw.reset()
        for sw_i in sw:
            if sw_i.getName().lower() == new_state:
                sw_i.setState(PyIndi.ISS_ON)
        self.sendNewSwitch(sw)

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
        if not self.tracking_active:
            return 'idle'

        sw = self.getProperty('Switch', 'TELESCOPE_TRACK_MODE')
        S = {sw_i.getLabel().lower()
             for sw_i in sw if sw_i.getState()==PyIndi.ISS_ON}
        if len(S) == 0:
            return None
        assert len(S) == 1, 'INDI Telescope in more than one tracking mode!!!'
        return S.pop()
    @tracking_mode.setter
    def tracking_mode(self, value):
        assert value in self.known_tracking_modes, \
          f'Unknown tracking mode: "{value}"'
        if value == 'idle':
            self.tracking_active = False
            return

        sw = self.getProperty('Switch', 'TELESCOPE_TRACK_MODE')
        sw.reset()
        for sw_i in sw:
            if sw_i.getLabel().lower() == value:
                sw_i.setState(PyIndi.ISS_ON)
        self.sendNewSwitch(sw)

        if not self.tracking_active:
            self.tracking_active = True

    def _movement_active(self):
        ra_dec = self.getProperty('Number', 'EQUATORIAL_EOD_COORD')
        return ra_dec.getState() == PyIndi.IPS_BUSY

    def _do_command_to_alt_az(self, alt, azi):
        """Command mount to slew to alt/az coordinates. Must be initialised.

        Args:
            alt (float): Altitude (degrees).
            azi (float): Azimuth (degrees) (in pypogs -180:180 ENU system).
        """
        loc = self.location
        if loc == None:
            raise RuntimeError('No geographic location set yet from INDI')
        azi = pypogs_az_to_INDI_az(azi)
        obstime = Time.now()
        altaz = SkyCoord(alt=alt*U.deg, az=azi*U.deg,
                         frame=AltAz(obstime=obstime, location=loc))
        radec = altaz.transform_to(FK5(equinox=obstime))
        ra_dec = self.getProperty('Number', 'EQUATORIAL_EOD_COORD')
        ra_dec[0].setValue(float(radec.ra.to(U.deg).value))
        ra_dec[1].setValue(float(radec.dec.to(U.deg).value))
        self.sendNewNumber(ra_dec)

    def updateProperty(self, p):
        """Emmited when new property is created for INDI driver"""
        if p.getDeviceName() != self.device_name:
            return

        if p.getName() == 'EQUATORIAL_EOD_COORD' and \
           p.getType() == PyIndi.INDI_NUMBER:
            N = p.getNumber()
            assert len(N) == 2, \
             f'INDI: unexpected length {len(N)} for equatorial coordinates'
            with self.lock:
                self._ra_dec = {ni.getName():ni.getValue() for ni in N}
                self._recent_updates += 1

        elif p.getName() == 'GEOGRAPHIC_COORD' and \
           p.getType() == PyIndi.INDI_NUMBER:
            N = p.getNumber()
            assert len(N) == 3, \
             f'INDI: unexpected length {len(N)} for geographic coordinates'
            with self.lock:
                self.location = [ni.getValue() for ni in N]
                self._recent_updates += 1
    newProperty = updateProperty

    @property
    def location(self):
        with self.lock:
            return self._location.copy() if self._location != None else None
    @location.setter
    def location(self, value):
        with self.lock:
            if isinstance(value, EarthLocation):
                self._location = value.copy()
            elif isinstance(value, (tuple, list)):
                assert len(value) == 3, \
                  'Invalid length for geographic coordinates'
                self._location = EarthLocation(lat = value[0],
                                               lon = value[1],
                                               height = value[2] * U.m)
            elif isinstance(value, dict):
                self._location = EarthLocation(lat = value['lat'],
                                               lon = value['lon'],
                                               height = value['height'] * U.m)
            else:
                raise ValueError('Unknown conversion to geographic coordinates')

    def handle_updates(self):
        with self.lock:
            loc = self.location
            if loc == None: # or self._recent_updates == 0:
                return

            # time to update position based on some update from hardware
            obstime = Time.now()
            coords = SkyCoord(ra = self._ra_dec['RA']*U.hourangle,
                              dec= self._ra_dec['DEC']*U.deg,
                              frame=FK5(equinox=obstime))
            altaz = coords.transform_to(AltAz(obstime=obstime, location=loc))
            self._altaz[:] = [float(altaz.alt.to(U.deg).value),
                              float(altaz.az.to(U.deg).value)]
            # mark that updates have been handled...
            self._total_updates_handled += self._recent_updates
            self._recent_updates = 0

            ## put into state cache with pypogs coords
            self._state_cache['alt'] = self._altaz[0]
            # Convert between INDI and pypogs frames (±180 ENU <--> 0-360° NEU)
            self._state_cache['azi'] = INDI_az_to_pypogs_az(self._altaz[1])

    @property
    def altaz_indi(self):
        """Get the current alt and azi angles of the mount in INDI coords."""
        with self.lock:
            self.handle_updates()
            return self._altaz.copy()

    @property
    def altaz_pypogs(self):
        """Get the current alt and azi angles of the mount in pypogs coords."""
        with self.lock:
            self.handle_updates()
            # handle_updates always updates cache immediately, just return
            return self._state_cache['alt'], self._state_cache['azi']

    @base.Mount.state_cache.getter
    def state_cache(self):
        self.handle_updates()
        return super().state_cache
    state_cache.__doc__ = base.Mount.state_cache.__doc__

    def _command_get_alt_az(self):
        """Get the current alt and azi angles of the mount.

        Returns:
            tuple of float: the (altitude, azimuth) angles of the mount in degrees (-180, 180].
        """
        return self.altaz_pypogs

    def _command_set_axis_rates(self, dalt, dazi):
        """
        Set the mount slew rates for altitude and azimuth.

        Should only be called by self.set_rate_alt_az.
        """
        if not self.has_custom_track_rate:
            raise NotImplementedError(
                'INDI Mount does not support setting custom tracking rates')

        tr = self.getProperty('Number', 'TELESCOPE_TRACK_RATE')
        old_rates = tr[0].getValue(), tr[1].getValue()

        if   self.mount_type == 'altaz':
            # can only find *some* hints online that we should just abuse the
            # naming of the TELESCOPE_TRACK_RATE properties and set them to
            # [0]=Azimuth, [1]=Altitude.
            # There do not seem to be any examples of drivers in the INDI
            # library where SetTrackRate is implemented for an ALTAX mount.  If
            # this assumption is not true, then the INDI Telescope must be able
            # to convert RA/DEC rates to ALTAZ rates internally.
            tr[0].setValue((dazi*U.deg/U.s).to(U.arcsec/U.s).value)
            tr[1].setValue((dalt*U.deg/U.s).to(U.arcsec/U.s).value)

        elif self.mount_type == 'eq_gem':
            # need to convert dalt, dazi to dRA and dDEC
            loc = self.location
            if loc == None:
                raise RuntimeError('No geographic location set yet from INDI')
            alt, azi = self.altaz_indi
            obstime = Time.now()
            altaz = SkyCoord(alt = alt*U.deg, az = azi*U.deg,
                             pm_alt      =dalt * U.deg/U.s,
                             pm_az_cosalt=dazi * np.cos(alt) * U.deg/U.s,
                             frame=AltAz(obstime=obstime, location=loc))
            print('INPUT alt,az,pm_alt,pm_az_cosalt: ', altaz.alt, altaz.az,
                  altaz.pm_alt, altaz.pm_az_cosalt)
            radec = altaz.transform_to(FK5(equinox=obstime))
            print('--> ra,dec,pm_dec,pm_ra_cosdec: ', radec.ra, radec.dec,
                  radec.pm_dec, radec.pm_ra_cosdec)
            _A = radec.transform_to(AltAz(obstime=obstime, location=loc))
            print('--> alt,az,pm_alt,pm_az_cosalt: ', _A.alt, _A.az,
                  _A.pm_alt, _A.pm_az_cosalt)

            tr[0].setValue((radec.pm_ra_cosdec / np.cos(radec.dec))
                           .to(U.arcsec/U.s).value)
            tr[1].setValue(radec.pm_dec.to(U.arcsec/U.s).value)
        else:
            raise NotImplementedError(
                f'Cannot send tracking rate to mount type "{self.mount_type}"')

        # INDI needs to be fixed a little for when tracking is enabled.  INDI
        # needs to be changed to send current rates to the driver upon enabling.
        new_rates = tr[0].getValue(), tr[1].getValue()
        if (new_rates[0]*old_rates[0] <0 or new_rates[1]*old_rates[1] <0) and \
           self.tracking_active:
            self._logger.warning('INDI: zeroing rates before sign-change; '
                                 '[%.03g, %.03g]->[%.03g, %.03g]', *old_rates,
                                 *new_rates)
            tr[0].setValue(0)
            tr[1].setValue(0)
            self.sendNewNumber(tr) # zero before changing
            tr[0].setValue(new_rates[0])
            tr[1].setValue(new_rates[1])

        self.sendNewNumber(tr)
        return dalt, dazi
