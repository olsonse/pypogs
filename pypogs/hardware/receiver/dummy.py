"""
Dummy implementation of a Receiver.

This allows instantiation, but certainly doesn't impact any hardware.
"""

import time, threading
import random

from . import base

class Receiver(base.Receiver):
    def __init__(self, *a, **kw):
        self._sample_rate = 1000.0
        self._range = [-10, 10]
        self._active = False
        super().__init__(*a, **kw)

    def set_identity(self, identity):
        self._identity = identity

    def _initialize(self):
        pass

    def _deinitialize(self):
        pass

    @property
    def active(self):
      return self._active

    @property
    def sample_rate(self):
        """int or float: Get or set the sample rate (in Hz) of the device. Must
        initialise the device first.
        """
        return self._sample_rate
    @sample_rate.setter
    def sample_rate(self, rate_hz):
        self._sample_rate = float(sample_rate)

    @property
    def measurement_range(self):
        return list(self._range)
    @measurement_range.setter
    def measurement_range(self, meas_range):
        assert not self.active, 'Measurement is already active'
        self._logger.debug('Setting measurement range to: '+str(meas_range))
        assert isinstance(meas_range, (int,float,tuple)), \
          'Input must be scalar (int/float) or a 2-tuple of scalars'
        if isinstance(meas_range,tuple):
            assert len(meas_range) == 2, \
              'Input must be scalar (int or float) or a 2-tuple of scalars'
            assert all( isinstance(x,(int,float)) for x in meas_range ), \
              'Input must be scalar (int or float) or a 2-tuple of scalars'
        else:
            meas_range = (-meas_range, meas_range)

        assert meas_range[0] <= meas_range[1], \
          'Measurement range must be (min, max) where min <= max'
        self._range[:] = meas_range[:]

    def _do_start(self):
        assert not self.active, 'Acquisition already running'
        self._logger.debug('Got start command')
        self._active = True

    def stop(self):
        assert self.active, 'Acquisition not running'
        self._logger.debug('Got stop command')
        self._active = False

    def _do_get_update_from_hardware(self):
        mn, mx = self.measurement_range
        return [random.uniform(mn, mx)]
