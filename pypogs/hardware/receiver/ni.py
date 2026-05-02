"""
NI-DAQmx implementation of a Receiver.
"""

import time, threading
import nidaqmx as ni

from . import base

class Receiver(base.Receiver):
    def __init__(self, *a, **kw):
        #Only used for NI DAQ devices
        self._ni_task = None
        super().__init__(*a, **kw)

    def set_identity(self, identity):
        self._logger.debug('Using NI DAQ, checking vailidity by opening a task')
        t = ni.Task()
        try:
            t.ai_channels.add_ai_voltage_chan(identity)
            self._identity = identity
        except ni.DaqError:
            self._logger.debug('Verification unsucessful', exc_info=True)
            raise AssertionError('The identity was not found')
        finally:
            try:
                self._logger.debug('Deleting task')
                t.close()
                del(t)
            except:
                self._logger.debug('Failed to delete task used to test identity', exc_info=True)

    def close(self):
        try:
            self._ni_task.close()
            del self._ni_task
            self._ni_task = None
            self._logger.debug('Closed the task')
        except:
            self._logger.debug('Failed to close task', exc_info=True)
    _deinitialize = close

    def _initialize(self):
        self._logger.debug('Using NI DAQ, create a task')
        try:
            self._ni_task = ni.Task(self.name) if self.name else ni.Task()
        except ni.DaqError:
            self._logger.debug('Failed to create task', exc_info=True)
            raise RuntimeError(
              'Failed to initialise, may conflict with existing instance')
        try:
            self._ni_task.ai_channels.add_ai_voltage_chan(self.identity)
            self._ni_task.timing.cfg_samp_clk_timing(
              rate=1000,
              sample_mode=ni.constants.AcquisitionType.CONTINUOUS
            )
            self._logger.info('Successfully initialised%s',
                              (': '+self.name) if self.name else '')
        except ni.DaqError:
            self._logger.debug('Failed to initialise', exc_info=True)
            self.close()
            raise RuntimeError(
              'Failed to initialise, may conflict with existing instance')

    @property
    def is_running(self):
        return self._ni_task and self._ni_task.is_task_done

    @property
    def sample_rate(self):
        """int or float: Get or set the sample rate (in Hz) of the device. Must
        initialise the device first.
        """
        self._logger.debug('Using NI DAQ, get sample rate')
        assert self._ni_task, 'NI Task expected to exist. Must initialize first'
        return self._ni_task.timing.samp_clk_rate
    @sample_rate.setter
    def sample_rate(self, rate_hz):
        self._logger.debug('NI DAQ: setting sample rate to (Hz): %s', rate_hz)
        assert self._ni_task, 'NI Task expected to exist. Must initialize first'
        assert not self.is_running, 'Cant change rate while running'

        self._logger.debug('Checking valid sample rate')
        rate_hz = float(rate_hz)
        mx = self._ni_task.timing.samp_clk_max_rate
        assert 0 < rate_hz <= mx, \
          f'Requested rate is not allowed, maximum rate is: {mx}'
        try:
            self._ni_task.timing.cfg_samp_clk_timing(
              rate=rate_hz, sample_mode=ni.constants.AcquisitionType.CONTINUOUS)
            self._logger.debug('Sampling rate set to: %g',
                               self._ni_task.timing.samp_clk_rate)
        except:
            self._logger.exception('Failed to set sample rate: ')
            raise

    @property
    def measurement_range(self):
        """tuple, int or float: Get or set upper/lower limits for measurements.

        - If given as a scalar the range will be set to +- the supplied value.
        """
        assert self._ni_task, 'NI Task expected to exist. Must initialize first'
        self._logger.debug('NI DAQ: Getting measurement range')
        try:
            return self._ni_task.ai_channels[0].ai_max, \
                   self._ni_task.ai_channels[0].ai_min
        except:
            self._logger.exception('Failed to get range')
            raise
    @measurement_range.setter
    def measurement_range(self, meas_range):
        assert self._ni_task, 'NI Task expected to exist. Must initialize first'
        assert not self.is_running, 'Cant change range while running'
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

        self._logger.debug('Decoded input: %s', meas_range)
        self._logger.debug('Using NI DAQ, trying to set')
        self._logger.debug('NOTE: nidaqmx is broken, must manually check if '
                           'range is allowed (-10, 10)...')
        assert meas_range[0] <= meas_range[1], \
          'Measurement range must be (min, max) where min <= max'
        assert min(meas_range)>=-10 and max(meas_range)<=10, \
          'Values must be <=10 and >=-10'
        self._logger.debug('NOTE: Passed manual value check')
        try:
            self._logger.debug('Setting new values')
            self._ni_task.ai_channels[0].ai_max = meas_range[1]
            self._ni_task.ai_channels[0].ai_min = meas_range[0]
            self._logger.debug('Range set to: %s', self.measurement_range)
        except ni.DaqError:
            self._logger.exception(
              'Failed to set new values, this may cause strange behaviour. '
              'De-init and re-init.')

    def _do_start(self):
        assert not self.is_running, 'Acquisition already running'
        self._logger.debug('Using NI DAQ, setting up callback')

        #Typically 10Hz, min 1 and max 1000 per callback:
        cb_count = int(min(1000, max(1, self.sample_rate/10)))

        def _ni_buffering_callback(task_handle, event_type, number_of_samples,
                                   callback_data):
            self._logger.debug('Got a callback')
            try:
                self._get_update_from_hardware()
            except:
                logging.error('Could not update from hardware')
            return 0

        try:
            self._ni_task.register_every_n_samples_acquired_into_buffer_event(
              cb_count, _ni_buffering_callback)
            self._logger.debug('Registered event every n=%d samples', cb_count)
        except ni.DaqError:
            self._logger.debug(
              'Unable to register event, trying to unregister and try again')
            self._ni_task.register_every_n_samples_acquired_into_buffer_event(
              cb_count, None)
            self._ni_task.register_every_n_samples_acquired_into_buffer_event(
              cb_count, _ni_buffering_callback)
            self._logger.debug('Registered event every n=%d samples', cb_count)
        self._ni_task.start()
        self._logger.info('Started acquisition from receiver')

    def stop(self):
        """Stop the acquisition. Will ensure all data in the buffer is read
        before stopping.
        """
        assert self.is_running, 'Acquisition is not running'
        self._logger.debug('NI DAQ: Got stop command')
        self._ni_task.stop()
        self._logger.debug('Stopped task')
        self._logger.info('Stopped acquisition from receiver')

    def _do_get_update_from_hardware(self):
        self._logger.debug('Using NI DAQ, reading all available')
        try:
            data = self._ni_task.read(ni.constants.READ_ALL_AVAILABLE)
            self._logger.debug('Data of length %d and class %s',
                               len(data), type(data))
        except:
            data = None
            if self.is_running:
                self._logger.exception('Failed to read data')
            else:
                self._loger.debug('Got a callback after stop command')
        return data
