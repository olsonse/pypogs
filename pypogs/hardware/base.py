# vim: ts=4:sw=4:tw=80:nowrap

import abc
from pathlib import Path
import logging

from . import factory as factory_module

class Hardware(abc.ABC):
    """Base abstract class for all hardware."""

    type = None # all hardware must use its own type (eg. 'mount', 'camera')

    @classmethod
    def factory(cls, model):
        """Lookup the class type in available mount types and return a class.

        Args:
            model (str): The model used to determine the the hardware control
                interface.

                Supported :class:`pypogs.Mount` models:
                    'Celestron' Celestron NexStar and Orion/SkyWatcher SynScan
                                (all the same) hand controller communication
                                over serial.
                    'ASCOM'     ASCOM-enabled telescope mounts.

                    'iOptron AZMP' Serially connected iOptron AZMP mounts.
                    'dummy'     Dummy (virtual) mount--mostly for debugging.

                Supported :class:`pypogs.Receiver` models:
                    'ni_daq'    National Instruments DAQ cards (tested on
                                USB-6211).
                    'dummy'     Dummy (virtual) receiver--mostly for debugging.

                Supported :class:`pypogs.Camera` models:
                    'ptgrey'    PointGrey/FLIR Machine Vision cameras (using
                                Spinnaker and PySpin).
        """
        return factory_module.factory(model, cls.type)

    @classmethod
    def available(cls):
        """Returns the list of available modules for this type of hardware."""
        return tuple(factory_module.available[cls.type])

    # Tuple of all available properties for this hardware.
    # Implementing hardware should include the base class available_properties
    available_properties = ('debug_folder',)

    def __init__(self, identity=None, name=None, auto_init=True, **properties):
        """
        Abstract base class for all Hardware.  Some properties can be defined by
        keyword arguments to the constructor.
        """
        self._is_init = False
        self._thread_prepped = False
        self._identity = None

        assert self.type != None, 'Implementing classes must define type'
        super().__init__()
        self.debug_folder = properties.pop(
          'debug_folder', Path(__file__).parent.parent.parent/'debug')

        self._logger = logging.getLogger('pypogs.hardware.' + self.type)
        if not self._logger.hasHandlers():
            # Add new handlers to the logger if there are none
            self._logger.setLevel(logging.DEBUG)
            # Console handler at INFO level
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            # File handler at DEBUG level
            fh = logging.FileHandler(self.debug_folder / 'pypogs.txt')
            fh.setLevel(logging.DEBUG)
            # Format and add
            formatter = logging.Formatter('%(asctime)s:%(name)s-%(levelname)s: '
                                          '%(message)s')
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)
            self._logger.addHandler(fh)
            self._logger.addHandler(ch)

        # Start of constructor
        self._logger.debug(
            'Hardware(%s, "%s") called with: identity=%s name=%s auto_init=%s',
            self.type, self.model, identity, name, auto_init)

        for k, v in properties.items():
            if k not in self.available_properties:
                continue
            self._logger.debug('Setting property "%s"="%s"', k, v)
            try:
                setattr(self, k, v)
            except:
                self._logger.warning('Failed to set property "%s"="%s"', k, v)

        self.name = name
        if identity:
            self.identity = identity
            if self.identity and auto_init:
                self.initialize() # model is already defined, so do init

        # Try to get Python to clean up the object properly
        import atexit, weakref
        atexit.register(weakref.ref(self.__del__))
        self._logger.info('Hardware(%s, "%s") instance created with name: %s',
                          self.type, self.model, self.name)

    def __del__(self):
        """Destructor, try to stop the Hardware and disconnect."""
        def trydebug(*a, **kw):
          try: self._logger.debug(*a, **kw)
          except: pass

        trydebug('Destructor called, try stop moving and disconnecting')
        try:
            self.stop()
            trydebug('Stopped')
        except: pass
        try:
            self.deinitialize()
            trydebug('Deinitialised')
        except: pass
        trydebug('Destructor finished')

    @property
    def model(self):
        """The model name for the particular device (as used by the factory)"""
        return factory_module.class_to_model(self)

    @property
    def name(self):
        """str: Get or set the name."""
        return self._name
    @name.setter
    def name(self, name):
        self._logger.debug('Setting name to: '+str(name))
        self._name = str(name)
        self._logger.debug('Name set to '+str(self.name))

    @property
    def debug_folder(self):
        """
        pathlib.Path: Get or set the path for debug logging. Will create folder
        if not existing.
        """
        return self._debug_folder
    @debug_folder.setter
    def debug_folder(self, path):
        # Do not do logging in here! This will be called before the logger is
        # set up
        path = Path(path)
        if path.is_file():
            path = path.parent
        if not path.is_dir():
            path.mkdir(parents=True)
        self._debug_folder = path

    @property
    def identity(self):
        """str: Get or set the device and/or input. Model must be defined first.

        - For model *celestron* or *iptron azmp* this can either be a string
          with the serial port (e.g. 'COM3' on Windows or '/dev/ttyUSB0' on
          Linux) or an int with the index in the list of available ports to use
          (e.g.  identity=0 i if only one serial device is connected.)
        - For model *ASCOM* this can either be left blank to invoke the ASCOM
          telescope selection menu, or may specify a specific installed ASCOM
          driver by name (case sensitive) (e.g. DeviceHub, Celestron, Simulator,
          SkyWatcher, etc).
        - Must set before initialising the device and may not be changed for an
          initialised device.

        Raises:
            AssertionError: if unable to connect to and verify identity of the
            hardware.
        """
        return self._identity
    @identity.setter
    def identity(self, identity):
        self._logger.debug('Hardware(%s) identity setter called with "%s"',
                           self.type, identity)
        assert not self.is_init, 'Can not change already initialised device'
        self.set_identity(identity)
        self._logger.debug('Identity set to: '+str(self.identity))

    @abc.abstractmethod
    def set_identity(self, identity):
        pass

    @property
    def is_init(self):
        return self._is_init

    def initialize(self):
        """Initialise (make ready to start) the device. The model and identity
        must be defined.
        """
        self._logger.debug('Initialising')
        assert not self.is_init, 'Already initialised'
        self._initialize()
        self._is_init = True
        self._logger.info('%s initialised.', self.type)
        self._post_initialize()

    def _post_initialize(self):
        """Possible function to implement by hardware implementations to run
        something after intialize is really complete."""
        pass

    @abc.abstractmethod
    def _initialize(self):
        """Do the actual initialization for the specific hardware"""
        pass

    def deinitialize(self):
        """
        De-initialise the device and release hardware (serial port). Will stop
        the Hardware if it is active.
        """
        self._logger.debug('De-initialising')
        assert self.is_init, 'Not initialised'
        try:
            self._logger.debug('Stopping %s', self.type)
            self.stop()
        except:
            self._logger.debug('Did not stop', exc_info=True)
        self._deinitialize()
        self._is_init = False
        self._logger.info('Deinitialised %s', self.type)

    @abc.abstractmethod
    def _deinitialize(self):
        """Do the actual de-initialization for the specific hardware"""
        pass

    def prep_thread_if_not_prepped(self):
        """
        Call any mount-specific code to allow comms on the current thread.  This
        is needed for ASCOM.
        """
        if not self._thread_prepped:
            self.prep_thread()
            self._thread_prepped = True

    def prep_thread(self):
        """
        Inheriting classes only need override the default no-op if necessary.
        """
        pass

    def unprep_thread_if_prepped(self):
        """
        Call any mount-specific code to uninit comms on the current thread.
        This is needed for ASCOM.
        """
        if self._thread_prepped:
            self.unprep_thread()
            self._thread_prepped = False

    def unprep_thread(self):
        """
        Inheriting classes only need override the default no-op if necessary.
        """
        pass

    @abc.abstractmethod
    def stop(self):
        """
        Stops all hardware activity for this device.
        """
        pass
