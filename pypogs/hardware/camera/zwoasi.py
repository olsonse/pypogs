"""
Implementation of a ZWO ASI camera.
"""

from pathlib import Path
from threading import Thread
import numpy as np
import zwoasi

from . import base

class Camera(base.ColorCapableCamera):
    ZWOASI_BAYER = {0:'RGGB', 1:'BGGR', 2:'GRBG', 3:'GBRG'}

    available_properties = base.Camera.available_properties + (
      'gain', 'gain_auto', 'exposure_time_auto',
    )

    defaults_to_set = dict(
      Exposure      = zwoasi.ASI_EXPOSURE,
      Gain          = zwoasi.ASI_GAIN,
      Flip          = zwoasi.ASI_FLIP,
      BandWidth     = zwoasi.ASI_BANDWIDTHOVERLOAD,
      HardwareBin   = zwoasi.ASI_HARDWARE_BIN,
      WB_B          = zwoasi.ASI_WB_B,
      WB_R          = zwoasi.ASI_WB_R,
      Offset        = zwoasi.ASI_OFFSET,
      HighSpeedMode = zwoasi.ASI_HIGH_SPEED_MODE,
      MonoBin       = zwoasi.ASI_MONO_BIN,
    )

    def __init__(self, *a, **kw):
        self._zwoasi_camera_index = None
        self._zwoasi_camera = None
        self._zwoasi_image_handler = None
        self._zwoasi_property = None
        super().__init__(*a, **kw)

    def set_identity(self, identity):
        self._logger.debug('Using zwoasi, first load and initialise the package')
        library_path = Path(__file__).parent.parent/'_system_data'/'ASICamera2'
        self._logger.debug('Initialising with files at %s', library_path.resolve())
        try:
            zwoasi.init(str(library_path.resolve()))
        except zwoasi.ZWO_Error as e:
            if not str(e) == 'Library already initialized':
                raise # Throw error if any other problem than already initialised

        self._logger.debug('Library intialised, checking if identity is available')

        # Get count and list of detected ZWO cameras:
        zwo_num_cameras = zwoasi.get_num_cameras()
        assert zwo_num_cameras > 0, 'No ZWO cameras detected.'
        zwo_camera_names = zwoasi.list_cameras()
        self._logger.info('Detected %d ZWO cameras: %s',
                       zwo_num_cameras, zwo_camera_names)

        # Derive ZWO camera index from identity:
        self._zwoasi_camera_index = None
        if identity is None:
            # Disallow for now. Later, consider populating a selection dialog.
            raise AssertionError('Identity is none')
        elif identity.isdigit():
            self._logger.info('specified camera identity as index (%s)',
                              identity)
            self._zwoasi_camera_index = int(identity)
        elif identity.lower().startswith('zwo') or \
             identity.lower().startswith('asi'):
            self._logger.info('specified camera identity by string (%s)',
                              identity)
            I = identity.lower().replace('zwo ', '')
            for i, cam in enumerate(zwo_camera_names):
                if cam.lower().replace('zwo ','') == I:
                    self._zwoasi_camera_index = i
                    break
        else:
            raise AssertionError('Unrecognized identity')

        self._logger.info('Selected ZWO camera: index %d, name "%s"',
                          self._zwoasi_camera_index,
                          zwo_camera_names[self._zwoasi_camera_index])
        assert self._zwoasi_camera_index is not None, \
          f'Unrecognized ZWO camera identity: "{identity}"'
        assert self._zwoasi_camera_index < zwo_num_cameras, \
          'Selected identity is greater than the available cameras,' \
          f'largest possible is one less than {num_cams}'

        # TODO: test if in use. Turns out API allows you to initialise several objects
        # connected to the same hardware without complaining... Must keep own list?

        #self._logger.debug('Identity available, testing if in use')
        #try...
        #self._zwoasi_camera = zwoasi.Camera(identity)

        #except...

        #finally... close

        self._identity = identity

    def _initialize(self):
        self._logger.debug('Using zwoasi, try to initialise')
        assert self._zwoasi_camera_index is not None, \
          'ZWO camera index not determined from identity'
        self._zwoasi_camera = zwoasi.Camera(self._zwoasi_camera_index)

        # Set to normal mode and 16 bit mode by default
        self._zwoasi_camera.set_camera_mode(zwoasi.ASI_MODE_NORMAL)
        self._zwoasi_camera.set_image_type(zwoasi.ASI_IMG_RAW16)

        self._zwoasi_property = self._zwoasi_camera.get_camera_property()

        # Set everything to default to be safe
        controls = self._zwoasi_camera.get_controls()
        for k, v in self.defaults_to_set.items():
            if k not in controls:
                continue # This model does not have this property, move along
            self._zwoasi_camera.set_control_value(v, controls[k]['DefaultValue'])

        self._zwoasi_image_handler = ZwoAsiImageHandler(self)

    def _deinitialize(self):
        self._logger.debug('Deinitialising zwoasi camera')
        self._zwoasi_camera.close()
        self._zwoasi_is_init = False
        self._zwoasi_camera = None
        self._zwoasi_property = None
        self._logger.debug('Closed, set deinit flag, deleted object')

    @property
    def flip_x(self):
        """bool: Get or set if the image X-axis should be flipped.
        Default is False.
        """
        self._logger.debug('Get flip-X called')
        assert self.is_init, 'Camera must be initialised'
        flipmode = self._zwoasi_camera.get_control_value(zwoasi.ASI_FLIP)[0]
        # mode 1 is flip horizontal, mode 3 is flip both:
        return (flipmode == 1) or (flipmode == 3)
    @flip_x.setter
    def flip_x(self, flip):
        self._logger.debug('Set flip-X called with: %s', flip)
        assert self.is_init, 'Camera must be initialised'
        flip = bool(flip)
        if not flip: # Disable horizontal flipping
            if not self.flip_y:
                # No flipping
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 0)
            else:
                # Set to only vertical flipping
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 2)
        else: # Enable horizontal flipping
            if not self.flip_y:
                # Flip only horizontal
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 1)
            else:
                # Flip both
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 3)

    @property
    def flip_y(self):
        """bool: Get or set if the image Y-axis should be flipped.
        Default is False.
        """
        self._logger.debug('Get flip-Y called')
        assert self.is_init, 'Camera must be initialised'
        flipmode = self._zwoasi_camera.get_control_value(zwoasi.ASI_FLIP)[0]
        # mode 2 is flip vertical, mode 3 is flip both:
        return (flipmode == 2) or (flipmode == 3)
    @flip_y.setter
    def flip_y(self, flip):
        self._logger.debug('Set flip-Y called with: %s', flip)
        assert self.is_init, 'Camera must be initialised'
        flip = bool(flip)
        if not flip: # Disable vertical flipping
            if not self.flip_x:
                # No flipping
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 0)
            else:
                # Set to only horizontal flipping
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 1)
        else: # Enable vertical flipping
            if not self.flip_x:
                # Flip only vertical
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 2)
            else:
                # Flip both
                self._zwoasi_camera.set_control_value(zwoasi.ASI_FLIP, 3)

    @property
    def frame_rate_auto(self):
        """bool: Get or set automatic frame rate.
        If True camera will run as fast as possible.
        """
        return True # Only auto frame rate available in normal mode

    @property
    def gain_auto(self):
        """bool: Get or set automatic gain.
        If True the gain will be continuously updated.
        """
        self._logger.debug('Get gain auto called')
        assert self.is_init, 'Camera must be initialised'
        return self._zwoasi_camera.get_control_value(zwoasi.ASI_GAIN)[1]
    @gain_auto.setter
    def gain_auto(self, auto):
        self._logger.debug('Set gain called with: '+str(auto))
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if not self.gain_auto == auto:
            self._logger.debug('Changing gain auto mode to: %s', auto)
            controls = self._zwoasi_camera.get_controls()
            default = controls['Gain']['DefaultValue']
            self._logger.debug(
              'Setting gain to auto %s and default: %s', auto, default)
            self._zwoasi_camera.set_control_value(zwoasi.ASI_GAIN, default, auto)
            self._logger.debug('Set gain auto to: %s', self.gain_auto)
        else:
            self._logger.warning(
              'Gain auto mode already set to: %s, doing nothing', auto)

    @property
    def gain_limit(self):
        """tuple of float: Get the minimum and maximum gain supported in the camera's native unit."""
        self._logger.debug('Get gain limit called')
        assert self.is_init, 'Camera must be initialised'
        self._logger.debug('Using zwoasi')
        controls = self._zwoasi_camera.get_controls()
        min = controls['Gain']['MinValue']
        max = controls['Gain']['MaxValue']
        self._logger.debug('Camera gave min %s and max %s', min, max)
        return (min, max)

    @property
    def gain(self):
        """float: Get or set the camera gain in the camera's native unit."""
        self._logger.debug('Get gain called')
        assert self.is_init, 'Camera must be initialised'
        return self._zwoasi_camera.get_control_value(zwoasi.ASI_GAIN)[0]
    @gain.setter
    def gain(self, gain):
        self._logger.debug('Set gain called with: %s', gain)
        assert self.is_init, 'Camera must be initialised'
        if self.gain_auto:
            self._logger.debug('Gain is set to auto. Command auto off')
            self.gain_auto = False
        self._logger.debug('Using zwoasi')
        self._zwoasi_camera.set_control_value(zwoasi.ASI_GAIN, int(gain))
        self._logger.debug('Set gain to %s', self.gain)

    @property
    def exposure_time_auto(self):
        """bool: Get or set automatic exposure time.

        If True the exposure time will be continuously updated.
        """
        self._logger.debug('Get exposure time auto called')
        assert self.is_init, 'Camera must be initialised'
        return self._zwoasi_camera.get_control_value(zwoasi.ASI_EXPOSURE)[1]
    @exposure_time_auto.setter
    def exposure_time_auto(self, auto):
        self._logger.debug('Set exposure time auto called with: %s', auto)
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if not self.exposure_time_auto == auto:
            self._logger.debug('Changing exposure auto mode to: %s', auto)
            controls = self._zwoasi_camera.get_controls()
            default = controls['Exposure']['DefaultValue']
            self._logger.debug('Setting exposure to auto %s and default: %s',
                               auto, default)
            self._zwoasi_camera.set_control_value(zwoasi.ASI_EXPOSURE, default, auto)
            self._logger.debug('Set exposure auto to: %s',
                               self.exposure_time_auto)
        else:
            self._logger.warning(
              'Exposure auto mode already set to: %s, doing nothing', auto)

    @property
    def exposure_time_limit(self):
        """tuple of float: Get the minimum and maximum expsure time in ms
        supported.
        """
        self._logger.debug('Get exposure time limit called')
        assert self.is_init, 'Camera must be initialised'
        controls = self._zwoasi_camera.get_controls()
        mn = controls['Exposure']['MinValue']
        mx = controls['Exposure']['MaxValue']
        self._logger.debug('Camera gave min %s and max %s', mn, mx)
        return (mn/1000, mx/1000)

    @property
    def exposure_time(self):
        """float: Get or set the camera expsure time in ms.

        Will set auto exposure time to False.
        """
        self._logger.debug('Get exposure time called')
        assert self.is_init, 'Camera must be initialised'
        # convert microseconds from zwoasi to ms:
        return self._zwoasi_camera.get_control_value(zwoasi.ASI_EXPOSURE)[0] / 1000
    @exposure_time.setter
    def exposure_time(self, exposure_ms):
        self._logger.debug('Set exposure time called with: %s', exposure_ms)
        assert self.is_init, 'Camera must be initialised'
        exposure_ms = float(exposure_ms)
        if self.exposure_time_auto:
            self._logger.debug('Exposure time is set to auto. Command auto off')
            self.exposure_time_auto = False
        self._logger.debug('Using zwoasi, setting to %d', int(exposure_ms*1000))
        self._zwoasi_camera.set_control_value(zwoasi.ASI_EXPOSURE, int(exposure_ms*1000))

    def _get_raw_size_max(self):
        """tuple of int: Get the maximum allowed readout size (width, height) in
        pixels.
        """
        assert self.is_init, 'Camera must be initialised'
        properties = self._zwoasi_camera.get_camera_property()
        bin = self.binning
        width = int(properties['MaxWidth'] / bin)
        width -= width % 8 # Must be multiple of 8
        height = int(properties['MaxHeight'] / bin)
        height -= height % 2 # Must be multiple of 2
        return width, height

    def _get_raw_size_readout(self):
        (width, height) = tuple(self._zwoasi_camera.get_roi_format()[:2])
        return width, height

    def set_roi(self, size, binning=None):
        self._logger.debug('ZWO set_roi adjust desired size to allowable size')
        size = [(round(size[0]) >> 3) << 3, # divisible by 8
                (round(size[1]) >> 1) << 1] # divisible by 2
        self._zwoasi_camera.set_roi(width = size[0], height = size[1],
                                    bins=binning)
        (w, h), bins = self.size_readout, self.binning
        self._logger.debug('Set readout to w=%d, h=%d, bins=%d', w, h, bins)
    _set_raw_size_readout = set_roi

    def _get_binning(self):
        return self._zwoasi_camera.get_bin()

    def _set_binning(self, binning):
        self._logger.debug(
          'Using zwoasi, width must be multiple of 8 and height multiple of 2')
        initial_size = self.size_readout
        if self.color_bin:
            initial_size = [2*x for x in initial_size]
        initial_bin = self.binning
        self._logger.debug('Initial binning and sensor readout area: %s, %s',
                           initial_bin, initial_size)

        # Calculate what the new ROI needs to be set to
        bin_scaling = binning/initial_bin
        new_size = [round(sz/bin_scaling) for sz in initial_size]

        self._logger.debug('New binning and new size to set: %s, %s',
                           binning, new_size)
        self.set_roi(new_size, binning)
        self._logger.debug('Set binning to %d and readout to %s',
                           self.binning, self.size_readout)

    @property
    def is_color_camera(self):
        return self._zwoasi_property['IsColorCam']

    def is_running(self):
        """bool: True if device is currently acquiring data."""
        if not self.is_init:
            return False
        return self._zwoasi_camera is not None and self._zwoasi_image_handler.is_running

    def _do_start(self):
        self._logger.debug('Calling start on zwoasi image handler')
        self._zwoasi_image_handler.start()

    def _do_stop(self):
        self._logger.debug('Calling stop on zwoasi image handler')
        self._zwoasi_image_handler.stop()


# Handler class to deal with the image stream
class ZwoAsiImageHandler:
    """Barebones class to start/stop camera and read images"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.log = parent._logger
        self._thread = None
        self._stop_running = False
    def start(self):
        self.log.info('Starting zwoasi imaging thread')
        self._thread = Thread(target = self._run)
        self._stop_running = False
        self._thread.start()
    def stop(self):
        self.log.info('Stopping zwoasi imaging thread')
        self._stop_running = True
        self._thread.join()
        self.parent._zwoasi_camera.stop_video_capture()
        self.log.info('zwoasi imaging thread has been stopped')
    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()
    def _run(self):
        """Start camera and continiously read out data"""
        cam = self.parent._zwoasi_camera
        cam.start_video_capture()
        timeout_ms = self.parent.exposure_time + 500
        debug = self.log.debug
        while not self._stop_running:
            try:
                img = cam.capture_video_frame(timeout = timeout_ms)
            except zwoasi.ZWO_IOError as e:
                if str(zwoasi.ZWO_IOError) == 'Camera closed':
                    debug('zwoasi Camera closed, probably deinitialising')
                else:
                    raise
            if self._stop_running:
                break

            debug('New image captured! Unpack and set image event')

            bayer_mode = 0
            if self.is_color_camera and len(img.shape) < 3:
                bayer_mode = self.parent._zwoasi_property['BayerPattern']

            img = self.parent.simple_image_processint(img,
              soft_ops=['rotate_90', 'debayer', 'grb_to_rgb'],
              color_pattern=self.ZWOASI_BAYER[bayer_mode])

            self.parent.new_image_frame(img)

        debug('Event handler finished.')
