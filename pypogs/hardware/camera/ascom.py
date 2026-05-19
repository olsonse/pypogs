"""
Implementation of a camera with an ASCOM interface.
"""

from threading import Thread
from time import sleep
import numpy as np

from . import base

class Camera(base.Camera):
    available_properties = base.Camera.available_properties + (
      'gain', 'exposure_time',
    )

    def __init__(self, *a, **kw):
        self._ascom_camera = None
        self._ascom_driver_handler = None
        self._exposure_sec = 0.1
        super().__init__(self, *a, **kw)

    def prep_thread(self):
        import pythoncom
        pythoncom.CoInitialize()

    def unprep_thread(self):
        import pythoncom
        pythoncom.CoUninitialize()

    def _ascom_release(self):
        """Release ASCOM hardware resources."""
        self._logger.debug('ASCOM camera release called')
        if self._ascom_camera is not None:
            if self._ascom_camera.Connected:
                if self._ascom_camera.CanAbortExposure:
                    self._ascom_camera.AbortExposure()
                self._ascom_camera.Connected = False
            self._logger.debug('ASCOM camera disconnected')
            self._ascom_pythoncom.CoUninitialize()
            self._ascom_camera = None
        self._logger.debug('ASCOM camera hardware released')

    def set_identity(self, identity):
        self._logger.debug('Checking ASCOM camera identity and availability')
        assert identity is not None, 'ASCOM camera identity not resolved'
        if not identity.startswith('ASCOM'):
            identity = 'ASCOM.'+identity+'.Camera'
        #self._logger.debug('Loading ASCOM camera driver: '+str(identity))
        #try:
        #    ascom_camera = self._ascom_driver_handler.Dispatch(identity)
        #except:
        #    raise RuntimeError('Failed to load camera driver')
        #if not ascom_camera or not hasattr(ascom_camera, 'Connected'):
        #    raise RuntimeError('Failed to load camera driver (2)')
        #if self._ascom_camera.Connected:
        #    self._logger.debug("Camera was already connected")
        #    raise RuntimeError('The camera is already in use')
        #else:
        #    self._logger.debug("Camera available. Setting identity.")
        self._identity = identity
        self._logger.debug('Specified identity: "%s" [%d]',
                           self.identity, len(self.identity))
        #ascom_camera = None

    @property
    def is_init(self):
        return hasattr(self, '_ascom_camera') and \
               self._ascom_camera is not None and self._ascom_camera.Connected

    def _initialize(self):
        if self._ascom_camera is not None:
            raise RuntimeError('There is already an ASCOM camera object here')
        self._logger.debug('Attempting to connect to ASCOM device "%s"',
                           self.identity)
        if self._ascom_driver_handler is None:
            import pythoncom
            self._ascom_pythoncom = pythoncom
            import win32com.client
            self._ascom_driver_handler = win32com.client

        camDriverName = str()
        if self.identity is not None:
            self._logger.debug('Specified identity: "%s" [%d]',
                               self.identity, len(self.identity))
            if self.identity.startswith('ASCOM'):
                camDriverName = self.identity
            else:
                camDriverName = 'ASCOM.'+str(self.identity)+'.Camera'
        else:
            ascomSelector = self._ascom_driver_handler.Dispatch("ASCOM.Utilities.Chooser")
            ascomSelector.DeviceType = 'Camera'
            camDriverName = ascomSelector.Choose('None')
            self._logger.info("Selected camera driver: %s", camDriverName)
            if not camDriverName:
                self._logger.debug('User canceled camera selection')
        assert camDriverName, 'Unable to identify ASCOM camera.'
        self._identity = camDriverName.replace('ASCOM.','').replace('.Camera','')

        self._logger.info('Loading ASCOM camera driver: %s', camDriverName)
        self._ascom_pythoncom.CoInitialize()

        try:
            self._ascom_camera = self._ascom_driver_handler.Dispatch(camDriverName)
        except self._ascom_pythoncom.com_error:
            raise AssertionError(
              f'Error attaching to device "{camDriverName}", check name.')

        assert hasattr(self._ascom_camera, 'Connected'), \
          "Unable to access camera driver"
        self._logger.debug('Connecting to camera')
        self._ascom_camera.Connected = True
        assert self._ascom_camera.Connected, "Failed to connect to camera"
        assert self._ascom_camera is not None, 'ASCOM camera not initialized'
        self._logger.debug('ReadoutMode: %s',
          self._ascom_camera.ReadoutModes[self._ascom_camera.ReadoutMode])
        self._logger.debug('SensorType: %s', self._ascom_camera.SensorType)
        self._logger.debug('CameraState: %s', self._ascom_camera.CameraState)

        self._ascom_camera_imaging_handler = AscomCameraImagingLoopHandler(self)
        self._ascom_camera_imaging_handler.start_imaging_loop()

    def _deinitialize(self):
        """De-initialise the device and release hardware resources. Will stop
        the acquisition if it is running.
        """
        self._ascom_release()

    @property
    def gain_limit(self):
        """tuple of float: Get the minimum and maximum gain supported in the
        camera's native unit.
        """
        self._logger.debug('Get gain limit called')
        assert self.is_init, 'Camera must be initialised'
        return (self._ascom_camera.GainMin, self._ascom_camera.GainMax)

    @property
    def gain(self):
        """float: Get or set the camera gain in the camera's native unit."""
        self._logger.debug('Get gain called')
        assert self.is_init, 'Camera must be initialised'
        return self._ascom_camera.Gain
    @gain.setter
    def gain(self, gain):
        self._logger.debug('Set gain called with: '+str(gain))
        assert self.is_init, 'Camera must be initialised'
        if self.gain_auto:
            self._logger.debug('Gain is set to auto. Command auto off')
            self.gain_auto = False
        mn, mx = self.gain_limit
        if not (mn <= gain <= mx):
            self._logger.debug(
              'Requested gain out of allowable range (%g:%g)', mn, mx)
            raise AssertionError(
              f'Requested gain [{gain}] out of allowable range ({mn}:{mx}).')
        self._ascom_camera.Gain = gain

    @property
    def exposure_time_limit(self):
        """tuple of float: Get the minimum and maximum expsure time in ms
        supported.
        """
        self._logger.debug('Get exposure time limit called')
        assert self.is_init, 'Camera must be initialised'
        return self._ascom_camera.ExposureMin, self._ascom_camera.ExposureMax

    @property
    def exposure_time(self):
        """float: Get or set the camera expsure time in ms.

        Will set auto exposure time to False.
        """
        self._logger.debug('Get exposure time called')
        assert self.is_init, 'Camera must be initialised'
        self._logger.debug('Returning '+str(self._exposure_sec*1000))
        return self._exposure_sec*1000
    @exposure_time.setter
    def exposure_time(self, exposure_ms):
        self._logger.debug('Set exposure time called with: '+str(exposure_ms))
        assert self.is_init, 'Camera must be initialised'
        exposure_ms = float(exposure_ms)
        if self.exposure_time_auto:
            self._logger.debug('Exposure time is set to auto. Command auto off')
            self.exposure_time_auto = False
        exposure_sec = exposure_ms/1000
        mn, mx = self._ascom_camera.ExposureMin, self._ascom_camera.ExposureMax

        if not (mn <= exposure_sec <= mx):
            self._logger.debug('Exposure time out of allowable range (%g:%g)',
                               mn, mx)
            raise AssertionError(
              f'Requested exposure time [{exposure_sec}] out of range.')
        self._exposure_sec = exposure_ms/1000

    @property
    def size_max(self):
        """tuple of int: Get the maximum allowed readout size (width, height) in
        pixels.
        """
        assert self.is_init, 'Camera must be initialised'
        try:
            val_w = self._ascom_camera.CameraXSize
            val_h = self._ascom_camera.CameraYSize
            return (val_w, val_h)
        except:
            self._logger.debug(
              'Unable to read ASCOM camera max image dimensions', exc_info=True)
            raise

    def _get_size_readout(self):
        try:
            val_w = self._ascom_camera.NumX
            val_h = self._ascom_camera.NumY
            return (val_w, val_h)
        except:
            self._logger.debug('Unable to read ASCOM camera image dimensions',
                               exc_info=True)

    def _set_size_readout(self, size):
        try:
            max_w = self._ascom_camera.CameraXSize
            max_h = self._ascom_camera.CameraYSize
            if not max_h or not max_w:
                raise AssertionError('Unable to read ASCOM camera image size limits.')
            try:
              bin_w = self._ascom_camera.BinX
              bin_h = self._ascom_camera.BinY
            except:
              raise AssertionError('Unable to read ASCOM camera binning value.')
            if not bin_h or not bin_w:
                raise AssertionError('Unable to read ASCOM camera binning value.')
            try:
                self._ascom_camera.NumX = max_w/bin_w
                self._ascom_camera.NumY = max_h/bin_h
            except:
                raise AssertionError('Unable to set ASCOM camera image size.')
        except:
            raise AssertionError('Unable to read ASCOM camera image size limits.')

    def _get_binning(self):
        try:
            val_horiz = self._ascom_camera.BinX
            val_vert = self._ascom_camera.BinY
            #self._logger.debug('Got '+str(val_horiz)+' '+str(val_vert))
            if val_horiz != val_vert:
                self._logger.warning('Horizontal & vertical binning not equal!')
            return val_horiz
        except PySpin.SpinnakerException:
            self._logger.warning('Failed to read binning property', exc_info=True)

    def _set_binning(self, binning):
        binMax = self._ascom_camera.MaxBinX
        if binMax and binning <= binMax:
            try:
                self._logger.info("setting binning to %i" % binning)
                self._ascom_camera.BinX = binning
                self._ascom_camera.BinY = binning
                self._ascom_camera.NumX = self._ascom_camera.CameraXSize/binning
                self._ascom_camera.NumY = self._ascom_camera.CameraYSize/binning
            except:
                raise AssertionError('Unable to set camera binning')
        else:
            raise ValueError('exceeds camera max bin val ',binMax)
        #bin_scaling = new_bin/initial_bin
        #new_size = [round(sz/bin_scaling) for sz in initial_size]
        #self._logger.debug('New binning and new size to set: '+str(new_bin)+' ,'+str(new_size))

    def is_running(self):
        """bool: True if device is currently acquiring data."""
        if not self.is_init:
            return False
        return self._ascom_camera.Connected and \
               self._ascom_camera_imaging_handler.is_running

    def _do_start(self):
        self._ascom_camera_imaging_handler.start_imaging_loop()

    def _do_stop(self):
        self._ascom_camera_imaging_handler.stop_imaging_loop()


class AscomCameraImagingLoopHandler:
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self._thread = None
        self._stop_running = False

    def start_imaging_loop(self):
        assert self.parent._ascom_camera, \
          'Cannot start imaging - camera not initialized'
        self.parent._logger.debug('Starting ASCOM camera imaging loop')
        self._thread = Thread(target=self.imaging_loop)
        self._stop_running = False
        self._thread.start()

    def stop_imaging_loop(self):
        debug = self.parent._logger.debug
        debug('Stopping ASCOM camera imaging loop')
        self._stop_running = True
        self._thread.join()
        debug('Stopped ASCOM camera imaging loop')

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def imaging_loop(self):
        assert self.parent._ascom_camera, \
          'Cannot start imaging - ASCOM camera driver not loaded'
        assert self.parent._ascom_camera.Connected, \
          'Cannot start imaging - ASCOM camera not connected'
        debug = self.parent._logger.debug
        debug('Starting ASCOM camera imaging loop')
        timeout = 0.5 # sec
        polling_period = 0.001 # sec
        while not self._stop_running and self.parent._ascom_camera.Connected:
            #debug('Starting ASCOM camera exposure')
            # Start exposure:
            self.parent._ascom_camera.StartExposure(self.parent._exposure_sec,True)

            # Wait for image to be ready:
            sleep(self.parent._exposure_sec * 0.95)
            waited_time = 0
            while not self.parent._ascom_camera.ImageReady and waited_time < timeout:
                sleep(polling_period)
                waited_time += polling_period
            if not self.parent._ascom_camera.ImageReady:
                debug('Timed out waiting for image')
                debug('Camera connected: %s', self.parent._ascom_camera.Connected)
                continue
            # Get and pre-process image:
            got_image = False
            try:
                img = np.array(self.parent._ascom_camera.ImageArray, dtype=np.float).copy().T
                img = self.parent.simple_image_processing(img)
            except:
                debug('Failed to access image.')
                img = None

            self.parent.new_image_frame(img)
            sleep(0.001)
        debug('Event handler finished.')
