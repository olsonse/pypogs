"""
Implementation of a pointgrey/FLIR camera as supported by the Spinnaker library.
"""

from datetime import datetime
from time import perf_counter as precision_timestamp
import numpy as np
from functools import cached_property

import gi
gi.require_version('Aravis', '0.8')
from gi.repository import Aravis

from . import base

class Camera(base.Camera):
    available_properties = base.Camera.available_properties + (
      'gain', 'frame_rate', 'gain_auto', 'frame_rate_auto',
      'exposure_time_auto', 'pixel_format',
    )

    SIMPLE_PIXEL_FORMATS = dict(Mono8=np.uint8, Mono16=np.uint16)

    # for now, a list of understood pixel formats.  Pixel format can be set to
    # the overlap between the available pixel formats for the camera and this
    # set.
    KNOWN_PIXEL_FORMATS = {'Mono16', 'Mono8'}

    def __init__(self, *a, **kw):
        # tell Aravis to discover connected devices
        self.camera = None
        self.pixel_format = 'Mono16'
        self.stream = None
        self.stream_fails = 0
        self.streaming = False
        super().__init__(*a, **kw)

    def _deinitialize(self):
        # camera should be stopped by now
        self._logger.debug('Deinitializing Aravis camera')
        try:
            self.stream.stop_thread(True)
            self._logger.debug('Stopped streaming thread')
        except:
            self._logger.exception('Failed to stop streaming thread')
        try:
            if hasattr(self, '_camera'):
              del self.camera
            if hasattr(self, '_stream'):
              del self.stream
            self.camera = None
            self.stream = None
            self.stream_fails = 0
            try: del self.region
            except: pass
            self._logger.debug('Deleted Aravis camera object')
        except:
            self._logger.exception('Failed to close task')
        self._logger.debug('Trying to release Aravis camera resources')

    def set_identity(self, identity):
        self._logger.debug('Using Aravis, checking vailidity')
        Aravis.update_device_list()
        all_device_ids = {
            Aravis.get_device_id(i) for i in range(Aravis.get_n_devices())}

        if identity not in all_device_ids:
            raise KeyError(f'Invalid Aravis camera identity: "{identity}"')
        self._identity = identity

    @property
    def is_init(self):
        return self.camera and self.stream

    def _initialize(self):
        assert self.identity is not None, \
          'Must define identity of Aravis camera before initialising'
        if self.camera:
            raise RuntimeError('Aravis: Unexpected existing camera object')
        self._logger.debug('Creating connection to Aravis camera')
        self.camera = Aravis.Camera.new(self.identity)
        # BASIC SETUP
        available = self.camera.dup_available_pixel_formats_as_strings()
        if self.pixel_format not in available:
            raise ValueError(
              f'Pixel format not available: "{self.pixel_format}"')
        self._logger.debug('Setting pixel format to %s', self.pixel_format)
        self.camera.set_pixel_format_from_string(self.pixel_format)

        if self.camera.is_feature_available('GammaEnable'):
          self._logger.debug('Setting gamma off')
          self.camera.set_boolean('GammaEnable', False)

        self._logger.debug('Setting acquisition mode to continuous')
        self.camera.set_string('AcquisitionMode', 'Continuous')

        self._logger.debug('Setting up Aravis streaming...')
        self.stream = self.camera.create_stream(self.stream_event_handler)
        payload = self.camera.get_payload()
        buf = Aravis.Buffer.new_allocate(payload)
        # give (at least temporary) ownership of buffer to stream:
        self.stream.push_buffer(buf)
        self._logger.info('Camera successfully initialised')

    @property
    def frame_rate_auto(self):
        """bool: Get or set automatic frame rate.

        If True camera will run as fast as possible.
        """
        self._logger.debug('Get frame rate auto called')
        assert self.is_init, 'Camera must be initialised'
        return self.camera.get_frame_rate_enable()
    @frame_rate_auto.setter
    def frame_rate_auto(self, auto):
        self._logger.debug('Set frame rate called with: %s', auto)
        assert self.is_init, 'Camera must be initialised'
        self.camera.set_frame_rate_enable(bool(auto))

    @property
    def frame_rate_limit(self):
        """tuple of float: Get the minimum and maximum frame rate in Hz
        supported."""
        self._logger.debug('Get frame rate limit called')
        assert self.is_init, 'Camera must be initialised'
        return tuple(self.camera.get_frame_rate_bounds())

    @property
    def frame_rate(self):
        """float: Get or set the camera frame rate in Hz. Will set auto frame
        rate to False."""
        self._logger.debug('Get frame rate called')
        assert self.is_init, 'Camera must be initialised'
        return self.camera.get_frame_rate()
    @frame_rate.setter
    def frame_rate(self, frame_rate_hz):
        self._logger.debug('Set frame rate called with: '+str(frame_rate_hz))
        assert self.is_init, 'Camera must be initialised'
        self.camera.set_frame_rate(float(frame_rate_hz))

    @property
    def gain_auto(self):
        """bool: Get or set automatic gain. If True the gain will be
        continuously updated.
        """
        self._logger.debug('Get gain auto called')
        assert self.is_init, 'Camera must be initialised'
        return self.camera.get_gain_auto() == Aravis.Auto.CONTINUOUS
    @gain_auto.setter
    def gain_auto(self, auto):
        self._logger.debug('Set gain called with: '+str(auto))
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if auto:
            set_to = Aravis.Auto.CONTINUOUS
        else:
            set_to = Aravis.Auto.OFF
        self._logger.debug('Will set gain auto to: %s', set_to)
        self.camera.set_gain_auto(set_to)

    @property
    def gain_limit(self):
        """tuple of float: Get the minimum and maximum gain supported in the
        camera's native unit.
        """
        self._logger.debug('Get gain limit called')
        assert self.is_init, 'Camera must be initialised'
        return tuple(self.camera.get_gain_bounds())

    @property
    def gain(self):
        """float: Get or set the camera gain in the camera's native unit."""
        self._logger.debug('Get gain called')
        assert self.is_init, 'Camera must be initialised'
        return self.camera.get_gain()
    @gain.setter
    def gain(self, gain):
        self._logger.debug('Set gain called with: %s', gain)
        assert self.is_init, 'Camera must be initialised'
        if self.gain_auto:
            self._logger.debug('Gain is set to auto. Command auto off')
            self.gain_auto = False
        self.camera.set_gain(gain)

    @property
    def exposure_time_auto(self):
        """bool: Get or set automatic exposure time.

        If True the exposure time will be continuously updated.
        """
        self._logger.debug('Get exposure time auto called')
        assert self.is_init, 'Camera must be initialised'
        if not self.camera.is_exposure_auto_available():
            return False
        return self.camera.get_exposure_time_auto() == Aravis.Auto.CONTINUOUS
    @exposure_time_auto.setter
    def exposure_time_auto(self, auto):
        self._logger.debug('Set exposure time auto called with: %s', auto)
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if auto:
            set_to = Aravis.Auto.CONTINUOUS
        else:
            set_to = Aravis.Auto.OFF
        self.camera.set_exposure_time_auto(set_to)

    @property
    def exposure_time_limit(self):
        """tuple of float: Get the minimum and maximum expsure time in ms
        supported.
        """
        self._logger.debug('Get exposure time limit called')
        assert self.is_init, 'Camera must be initialised'
        lim_us = self.camera.get_exposure_time_bounds()
        return lim_us.min/1000.0, lim_us.max/1000.0

    @property
    def exposure_time(self):
        """float: Get or set the camera expsure time in ms.

        Will set auto exposure time to False.
        """
        self._logger.debug('Get exposure time called')
        assert self.is_init, 'Camera must be initialised'
        return self.camera.get_exposure_time() / 1000.0
    @exposure_time.setter
    def exposure_time(self, exposure_ms):
        self._logger.debug('Set exposure time called with: '+str(exposure_ms))
        assert self.is_init, 'Camera must be initialised'
        exposure_ms = float(exposure_ms)
        if self.exposure_time_auto:
            self._logger.debug('Exposure time is set to auto. Command auto off')
            self.exposure_time_auto = False
        self.camera.set_exposure_time(exposure_ms * 1000.0)

    @property
    def size_max(self):
        """tuple of int: Get the maximum allowed readout size (width, height) in
        pixels.

        For at least some of FLIR/Point-Grey cameras, this value considers the
        current binning setting, thus will not equal SensorWidth/SensorHeight.
        """
        assert self.is_init, 'Camera must be initialised'
        w_lim = self.camera.get_width_bounds()
        h_lim = self.camera.get_height_bounds()
        return w_lim.max, h_lim.max

    def _get_size_readout(self):
        r = self.region
        return r.width, r.height

    @cached_property
    def region(self):
        return self.camera.get_region()

    def _set_size_readout(self, size):
        wi = self.camera.get_width_increment()
        hi = self.camera.get_height_increment()
        xi = self.camera.get_x_offset_increment()
        yi = self.camera.get_y_offset_increment()

        size = [round(size[0] / wi) * wi, round(size[1] / hi) * hi]
        max_size = self.size_max
        offs = [round((max_size[0] - size[0]) / 2),
                round((max_size[1] - size[1]) / 2)]
        offs = [round(offs[0] / xi) * xi, round(offs[1] / yi) * yi]
        self.camera.set_region(x=offs[0], y=offs[1],
                                width=size[0], height=size[1])
        # remove any possible cached region property:
        try: del self.region
        except: pass

    def _get_binning(self):
        """int: Number of pixels to bin in each dimension (e.g. 2 gives 2x2
        binning);

        *ptgrey* cameras bin by summing, *zwoasi* cameras bin by averaging.

        Setting will stop and restart camera if running. Will scale size_readout
        to show the same sensor area.
        """
        if self.camera.is_binning_available():
            b = self.camera.get_binning()
            if b.dx != b.dy:
                self._logger.warning('Horizontal & vertical binning not equal!')
            return b.dx
        return 1

    def _set_binning(self, binning):
        """Keep effective region of interest constant while changing binning."""
        initial_size = self.size_readout
        initial_bin = self.binning
        self._logger.debug('Initial binning and sensor readout area: %s, %s',
                           initial_bin, initial_size)
        bxi = self.camera.get_x_binning_increment()
        byi = self.camera.get_y_binning_increment()
        bx_lim = self.camera.get_x_binning_bounds()
        by_lim = self.camera.get_y_binning_bounds()

        # force binning to be on proper grid and limited as per hardware specs
        binning = [max(bx_lim.min, min(bx_lim.max, round(binning / bxi) * bxi)),
                   max(by_lim.min, min(by_lim.max, round(binning / byi) * byi))]
        if binning[0] != binning[1]:
            self._logger.warning(
              'Horizontal and vertical binning not commensurate; trying anyway')

        # Calculate what the new ROI needs to be set to
        bin_scaling = binning[0]/initial_bin
        new_size = [round(sz/bin_scaling) for sz in initial_size]

        self.camera.set_binning(*binning)
        self.size_readout = new_size

    @property
    def pixel_format(self):
        return self._pixel_format
    @pixel_format.setter
    def pixel_format(self, value):
        assert not self.is_init, 'Camera must *NOT* be initialised'
        if value not in self.KNOWN_PIXEL_FORMATS:
            raise NotImplementedError(f'Unimplemented pixel format: "{value}"')
        self._pixel_format = value

    @property
    def is_running(self):
        """bool: True if device is currently acquiring data."""
        if not self.is_init:
            return False
        return self.camera and self.stream and self.streaming

    def _do_start(self):
        self.camera.start_acquisition()
        self.streaming = True

    def _do_stop(self):
        self.camera.stop_acquisition()
        self.streaming = False

    def stream_event_handler(self, callback_type, buf):
        """Read out the image and a timestamp, reshape to array, keep copy."""
        if callback_type != Aravis.StreamCallbackType.BUFFER_DONE:
            return

        b0 = self.stream.pop_buffer()
        assert b0 == buf, 'popped buffer does not match callback arg'

        try:
            if buf.get_status() != Aravis.BufferStatus.SUCCESS:
                self.stream_fails += 1

            # using the correct pixel format, convert to numpy ndarray and copy
            if self.pixel_format not in self.SIMPLE_PIXEL_FORMATS:
                # this really shouldn't ever happen by this point
                raise NotImplementedError(
                  f'Unimplemented pixel format: {self.pixel_format}')

            # these pixel formats are very easy
            dtype = self.SIMPLE_PIXEL_FORMATS[self.pixel_format]
            img_data = buf.get_data()
            if len(img_data) == 0:
                self._logger.warning('Empty buffer received from stream!')
                self._image_data = None
                return

            img = np.frombuffer(img_data, dtype=dtype) \
                .reshape(self.region.height, self.region.width).copy()
            img = self.simple_image_processing(img)

            self._logger.debug('Image event!')
            self._image_timestamp = datetime.utcnow()
            self._image_data = img

        except:
            self._logger.warning('Failed to unpack image', exc_info=True)
            self._image_data = None
            return
        finally:
            # be sure to add the buffer back to the stream for new frames
            self.stream.push_buffer(buf)

        last_timestamp = self._image_precision_timestamp
        self._image_precision_timestamp = precision_timestamp()
        self._imgs_since_start += 1

        self._got_image_event.set()
        self._logger.debug('Time: %s Size:%s Type:%s',
                                  self._image_timestamp,
                                  self._image_data.shape,
                                  self._image_data.dtype)
        for func in self._call_on_image:
            try:
                #self._logger.debug('Calling back to: %s', func)
                func(self._image_data, self._image_timestamp)
            except:
                self._logger.warning('Failed image callback', exc_info=True)
        if last_timestamp is not None:
            new_frame_time = self._image_precision_timestamp - last_timestamp
            if self._average_frame_time is None:
                self._average_frame_time = new_frame_time
            else:
                # computing a simple exponential average
                self._average_frame_time = \
                  .8*self._average_frame_time + .2*new_frame_time

        self._logger.debug('Image read callback finished.')
