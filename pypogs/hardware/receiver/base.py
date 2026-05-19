# vim: ts=4:sw=4:tw=80:nowrap

import abc
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, UTC
from struct import pack as pack_data

from .. import base
from .. import factory as factory_module

class Receiver(base.Hardware):
    """Control acquisition and read received power from a photodetector.

    To intantiate a Receiver, the *model* (determines hardware interface) must
    be given to the Receiver.factory.  To initialise a Receiver, an *identity*
    (identifying the specific device) must be given. If the identity is given to
    the constructor, the Receiver will be initialised immediately (unless
    auto_init=False is passed). Manually initialise with a call to
    Receiver.initialize(); release hardware with a call to
    Receiver.deinitialize().

    The raw data can be saved to a file by specifying data_folder (filenames are
    auto-generated). While the acquisition is running the instantaneous (last
    measurement) and (exponentially) smoothed power can be read.

    Mount implementations are not intended to be imported or instantiated
    directly, but rather through the :meth:`pypogs.Receiver.factory` class
    method.

    Args:
        identity (str, optional): String identifying the device and input. For
            *ni_daq* this is 'device/input' eg.  'Dev1/ai1' for device 'Dev1'
            and analog input 1; only differential input is supported for
            *ni_daq*.
        name (str, optional): Name for the device.
        auto_init (bool, optional): If both model and identity are given when
            creating the Receiver and auto_init is True (the default),
            Receiver.initialize() will be called after creation.
        data_folder (pathlib.Path, optional): The folder for data saving. If
            None (the default) no data will be saved.
        debug_folder (pathlib.Path, optional): The folder for debug logging. If
            None (the default) the folder *pypogs*/debug will be used/created.

    Example:
        ::

            # Create instance and set parameters (will auto initialise)
            rec = pypogs.Receiver.factory('ni_daq').(identity='Dev1/ai1', name='PhotoDiode')
            rec.sample_rate = 1000 #Samples per second
            rec.smoothing_parameter = 100 #number of samples to smooth over
            rec.measurement_range = (-10, 10) #Volts for ni_daq
            # Add a save path (filenames are auto-generated)
            rec.data_folder = pathlib.Path('./datafolder')
            # Start acquisition
            rec.start()
            # Wait for a while
            time.sleep(2)
            # Read the smooth and instantaneous powers
            print('Smoothed power is: ' + str(rec.smooth_power))
            print('Instant power is: ' + str(rec.instant_power))
            # Stop the acquisition
            rec.stop()
    """

    type = 'receiver'

    #
    # Set of all available properties for this device.
    # Child classes can add to this, override this with a class value, or with a
    # @property.
    available_properties = (
      'sample_rate', 'measurement_range', 'smoothing_parameter', 'data_folder',
    ) + base.Hardware.available_properties

    def __init__(self, *a, **kw):
        """
        Abstract base class constructor for all receivers.  Some receiver
        properties can be defined by keyword arguments to the receiver
        constructor.
        """
        self._data_folder = None
        self._data_file = None
        # Power values stored from the receiver
        self._instant_power = None
        self._smooth_power = None
        self._smoothing_parameter = 100
        super().__init__(*a, **kw)

    @property
    def data_folder(self):
        """pathlib.Path: Get or set the path for data saving. Will create folder
        if not existing.
        """
        return self._data_folder
    @data_folder.setter
    def data_folder(self, path):
        self._logger.debug('Got set data folder with: %s', path)
        path = Path(path)
        if path.is_file():
            path = path.parent
        if not path.is_dir():
            path.mkdir(parents=True)
        self._data_folder = path
        self._logger.debug('Set data folder to: %s', self.data_folder)

    @abc.abstractproperty
    def sample_rate(self):
        """int or float: Get or set the sample rate (in Hz) of the device.
        Must initialise the device first.
        """
        pass

    @abc.abstractproperty
    def measurement_range(self):
        """tuple, int or float: Get or set upper/lower limits for measurements.

        - If given as a scalar the range will be set to +- the supplied value.
        """
        pass

    @property
    def smoothing_parameter(self):
        """int or float: Get or set the smoothing parameter. It roughly corresponds to the number of samples to average.

        - Exponential smoothing is used. smoothing_parameter is the *inverse* of 'alpha'. Each smoothed value s is
          defined from the measurements x by:

              ``s[n] = alpha*x[n] + (1-alpha)*s[n-1]; s[0] = x[0]``
        """
        return self._smoothing_parameter
    @smoothing_parameter.setter
    def smoothing_parameter(self, param):
        assert isinstance(param, (int, float)), 'Parameter must be scalar (float or int)'
        assert param > 0, 'Parameter must be >0'
        self._smoothing_parameter = param
        self._logger.debug('Smoothing parameter set to '+str(param))

    @property
    def instant_power(self):
        """float: Get the latest raw measurement."""
        if not self.is_running: return None
        self._get_update_from_hardware()
        return self._instant_power

    @property
    def smooth_power(self):
        """float: Get the current smoothed measurement (see smoothing_parameter)."""
        if not self.is_running: return None
        self._get_update_from_hardware()
        return self._smooth_power

    def start(self):
        """Start the acquisition. Device must be initialised.
        Data will only be saved if data_folder is set.
        """
        assert self.is_init, 'Must initialise first'
        self._logger.debug('Got start command')
        if self.data_folder is not None:
            self._logger.debug('Data folder exists, creating file and header')
            self._create_data_file()
        else:
            self._logger.debug('No save path set')
        self._do_start()

    @abc.abstractmethod
    def _do_start(self):
        """Start the acquisition. Device must be initialised.
        Data will only be saved if data_folder is set.
        """
        pass

    @abc.abstractmethod
    def stop(self):
        """Stop the acquisition. Will ensure all data in the buffer is read
        before stopping.
        """
        pass

    def _get_update_from_hardware(self):
        """Read all available data from the device and call
        _update_stored_values. Save if data_folder is set.
        """
        data = self._do_get_update_from_hardware()
        if data:
            try:
                self._update_stored_values(data)
            except:
                self._logger.exception('Failed to update stored values')
            if self.data_folder is not None:
                try:
                    self._write_data_to_data_file(data)
                except:
                    self._logger.exception('Failed to save update')

    @abc.abstractmethod
    def _do_get_update_from_hardware(self):
        pass

    def _update_stored_values(self, data):
        """Update the stored instantaneous and smoothed measurement."""
        self._logger.debug('Got update request with length '+str(len(data)))
        if None in (self._smooth_power, self._instant_power):
            #No old data, need to initialise
            self._logger.debug('No previous values')
            self._instant_power = data[-1] #Last read data saved here
            if len(data) == 1: #If only one point
                self._smooth_power = data[0]
            else:
                k = len(data)
                a = 1/self._smoothing_parameter
                data = np.array(data)
                facs = (1-a)**np.arange(k) #Smoothing factors
                self._smooth_power = a*np.sum(facs[:-1] * data[:-1]) \
                                   + facs[-1]*data[-1]
        else: #Doing a normal update
            self._logger.debug('Previous smooth and instant powers are: %s %s',
                               self._smooth_power, self._instant_power)
            self._instant_power = data[-1] #Last read data saved here
            k = len(data)
            a = 1/self._smoothing_parameter
            if k == 1: #If only one point
                self._smooth_power = a*data[0] + (1-a)*self._smooth_power
            else:
                data = np.array(data)
                facs = (1-a)**np.arange(k+1) #Smoothing factors
                self._smooth_power = a*np.sum(facs[:-1] * data) \
                                   + facs[-1]*self._smooth_power

        self._logger.debug('Smooth and instant power are now: %s %s',
                           self._smooth_power, self._instant_power)

    def _write_data_to_data_file(self, data):
        """Write data to the data file."""
        self._logger.debug('Writing to data file, got %d measurements',
                           len(data))
        assert self._data_file is not None, 'No logfile is defined...'
        with open(self._data_file, 'ba') as file:
            #Create and write binary (dobule) representation of data
            file.write(pack_data('%df' % len(data), *data))

    def _create_data_file(self):
        """"Create data file and write the header."""
        assert self.data_folder is not None, 'No save path here...'
        self._logger.debug('Creating data file')
        timestamp = datetime.now(UTC)
        filename = timestamp.strftime('%Y-%m-%dT%H%M%S') + '_Receiver.dat'
        self._data_file = self.data_folder / Path(filename)
        self._logger.debug('File: ' + str(filename))
        header = (f'TIME: {timestamp.isoformat()}; '
                  f'NAME: {self.name}; '
                  f'MODEL: {self.model}; '
                  f'IDENTITY: {self.identity}; '
                  f'SAMPLE_RATE: {self.sample_rate}; '
                  f'MEASUREMENT_RANGE: {self.measurement_range}; '
                  'FORMAT: STRUCT_PACK_FLOAT32;\n')

        self._logger.debug('Header: ' + header)
        with open(self._data_file, 'a') as file:
            file.write(header)
