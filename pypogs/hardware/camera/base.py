# vim: ts=4:sw=4:tw=80:nowrap

import abc
from threading import Event
from datetime import datetime, UTC
from time import perf_counter as precision_timestamp

from .. import base
from .. import factory as factory_module
from .color import debayer_image

class Camera(base.Hardware):
    """Control acquisition and receive images from a camera.

    To initialise a Camera a *model* (determines hardware interface) and
    *identity* (identifying the specific device) must be given. If both are
    given to the constructor the Camera will be initialised immediately (unless
    auto_init=False is passed). Manually initialise with a call to
    Camera.initialize(); release hardware with a call to Camera.deinitialize().

    After the Camera is initialised, acquisition properties (e.g. exposure_time
    and frame_rate) may be set and images received. The Camera also supports
    event-driven acquisition, see Camera.add_event_callback(), where new images
    are automatically passed on to the desired functions.

    Mount implementations are not intended to be imported or instantiated
    directly, but rather through the :meth:`pypogs.Camera.factory` class method.

    Args:
        model (str, optional): The model used to determine the correct hardware
            API. Supported: 'ptgrey' for PointGrey/FLIR Machine Vision cameras
            (using Spinnaker and PySpin).  identity (str, optional): String
            identifying the device. For model *ptgrey* this is 'serial number'
            *as a string*.
        name (str, optional): Name for the device.
        auto_init (bool, optional): If both model and identity are given when
            creating the Camera and auto_init is True (the default),
            Camera.initialize() will be called after creation.
        debug_folder (pathlib.Path, optional): The folder for debug logging. If
            None (the default) the folder *pypogs*/debug will be used/created.

    Example:
        ::

            # Create instance and set parameters (will auto initialise)
            cam = pypogs.Camera.factory('ptgrey').(identity='18285284', name='CoarseCam')
            cam.gain = 0 #decibel
            cam.exposure_time = 100 #milliseconds
            cam.frame_rate_auto = True
            # Start acquisition
            cam.start()
            # Wait for a while
            time.sleep(2)
            # Read the latest image
            img = cam.get_latest_image()
            # Stop the acquisition
            cam.stop()
            # Release the hardware
            cam.deinitialize()
    """

    type = 'camera'

    #
    # Set of all available properties for this device.
    # Child classes can add to this, override this with a class value, or with a
    # @property.
    available_properties = (
      'flip_x', 'flip_y', 'rotate_90', 'plate_scale', 'rotation', 'binning',
      'size_readout', 'exposure_time',
    ) + base.Hardware.available_properties

    def __init__(self, *a, **kw):
        """
        Abstract base class constructor for all Cameras.  Some camera
        properties can be defined by keyword arguments to the Camera
        constructor.
        """
        self._plate_scale = 1.0
        self._rotation = 0.0
        self._flipX = False
        self._flipY = False
        self._rot90 = 0 #Number of times to rotate by 90 deg, done after flips

        #Callbacks on image event
        self._call_on_image = set()
        self._got_image_event = Event()
        self._image_data = None
        self._image_timestamp = None
        self._imgs_since_start = 0
        self._average_frame_time = None  # Running average of time between frames in ms
        self._image_precision_timestamp = None  # Precision timestamp of last frame
        super().__init__(*a, **kw)

    @property
    def flip_x(self):
        """bool: Get or set if the image X-axis should be flipped.
        Default is False.
        """
        return self._flipX
    @flip_x.setter
    def flip_x(self, flip):
        self._flipX = bool(flip)

    @property
    def flip_y(self):
        """bool: Get or set if the image Y-axis should be flipped.
        Default is False.
        """
        return self._flipY
    @flip_y.setter
    def flip_y(self, flip):
            self._flipY = bool(flip)

    @property
    def rotate_90(self):
        """int: Get or set how many times the image should be rotated by 90
        degrees.

        Applied *after* flip_x and flip_y.
        """
        return self._rot90
    @rotate_90.setter
    def rotate_90(self, k):
        self._rot90 = int(k)

    @property
    def plate_scale(self):
        """float: Get or set the plate scale of the Camera in arcsec per pixel.

        This will not affect anything in this class but is used elsewhere. Set
        this to the physical pixel plate scale *before* any binning. When
        getting the plate scale it will be scaled by the binning factor.
        """
        return self._plate_scale * self.binning
    @plate_scale.setter
    def plate_scale(self, arcsec):
        self._logger.debug('Set plate scale called with: %g', arcsec)
        self._plate_scale = float(arcsec)
        self._logger.debug('Plate scale set to: %g', self.plate_scale)

    @property
    def rotation(self):
        """float: Get or set the camera rotation relative to the horizon in
        degrees.

        This does not affect the received images, but is used elsewhere. Use
        rotate_90 first to keep this rotation small.
        """
        return self._rotation
    @rotation.setter
    def rotation(self, rot):
        self._logger.debug('Set rotation called with: %g', rot)
        self._rotation = float(rot)
        self._logger.debug('Rotation set to: %g', self.rotation)

    @property
    def frame_rate_actual(self):
        """float: Get the actual image frame rate in Hz.

        Returns None if not running.
        """
        with self.lock:
            tavg = self._average_frame_time
            return 1/tavg if tavg is not None else None

    @property
    def binning(self):
        """int: Number of pixels to bin in each dimension (e.g. 2 gives 2x2
        binning);

        *ptgrey* cameras bin by summing, *zwoasi* cameras bin by averaging.

        Setting will stop and restart camera if running. Will scale size_readout
        to show the same sensor area.
        """
        assert self.is_init, 'Camera must be initialised'
        return self._get_binning()
    @binning.setter
    def binning(self, binning):
        self._logger.debug('Set binning called with: %s', binning)
        assert self.is_init, 'Camera must be initialised'
        was_running = self.is_running
        if self.is_running:
            self._logger.debug('Camera is running, stop it and restart immediately after.')
            self.stop()

        # make call to child implementation to actually apply settings
        # _set_binning is expected to adjust frame size to keep ROI the same
        self._set_binning(int(binning))

        if was_running:
            self._logger.debug('Restarting camera imaging loop.')
            try:
                self.start()
                self._logger.debug('Restarted')
            except Exception:
                self._logger.debug('Failed to restart: ', exc_info=True)
        else:
            self._logger.debug('Camera imaging loop was not previously running.')

    @abc.abstractmethod
    def _get_binning(self):
        pass

    @abc.abstractmethod
    def _set_binning(self, binning):
        """
        Set the binning and also adjust the frame size in order to keep the ROI
        the same.
        """
        pass

    @property
    def size_readout(self):
        """tuple of int: Get or set the number of pixels read out (width, height).

        Changing size_readout will automatically center the image (ie. x/y
        offset are automatically computed and set).

        This applies after binning, i.e. this is the size the output image will
        be.

        For model *zwoasi* the set size will be rounded down to the nearest
        multiple of 8 in width and 2 in height.

        Setting will stop and restart camera if running.
        """
        assert self.is_init, 'Camera must be initialised'
        return self._get_size_readout()
    @size_readout.setter
    def size_readout(self, size):
        assert self.is_init, 'Camera must be initialised'
        self._logger.debug('Got set readout with: ' + str(size))
        if isinstance(size, (int, float)):
            size = (size, size)
        size = tuple([int(x) for x in size])
        was_running = self.is_running
        if self.is_running:
            self._logger.debug('Camera is running, stop it and restart immediately after.')
            self.stop()

        # make call to child implementation to actually apply settings
        self._set_size_readout(size)

        if was_running:
            try:
                self.start()
                self._logger.debug('Restarted')
            except Exception:
                self._logger.debug('Failed to restart: ', exc_info=True)

    @abc.abstractmethod
    def _get_size_readout(self):
        pass

    @abc.abstractmethod
    def _set_size_readout(self, size):
        pass

    @abc.abstractproperty
    def exposure_time(self):
        """float: Get or set the camera exposure time in ms.
        """
        pass

    def add_event_callback(self, method):
        r"""Add a method to be called when a new image shows up.

        The method should have the signature (image, timestamp, \*args, \*\*kwargs) where:

        - image (numpy.ndarray): The image data as a 2D numpy array.
        - timestamp (datetime.datetime): UTC timestamp when the image event occurred (i.e. when the capture
          finished).
        - \*args, \*\*kwargs should be allowed for forward compatibility.

        The callback should *not* be used for computations, make sure the method returns as fast as possible.

        Args:
            method: The method to be called, with signature (image, timestamp, \*args, \*\*kwargs).
        """
        self._logger.debug('Adding to callbacks: ' + str(method))
        with self.lock:
            self._call_on_image.add(method)

    def remove_event_callback(self, method):
        """Remove method from event callbacks."""
        try:
            with self.lock:
                self._call_on_image.remove(method)
        except:
            self._logger.warning('Could not remove callback', exc_info=True)

    @abc.abstractproperty
    def is_running(self):
        """bool: True if device is currently acquiring data."""
        pass

    def start(self):
        """Start the acquisition. Device must be initialised."""
        assert self.is_init, 'Must initialise first'
        if self.is_running:
            self._logger.info('Camera already running, name: '+self.name)
            return
        self._logger.debug('Got start command')
        self._imgs_since_start = 0
        self._do_start()
        self._logger.info('Acquisition started, name: '+self.name)

    @abc.abstractmethod
    def _do_start(self):
        pass

    def stop(self):
        """Stop the acquisition."""
        self._logger.debug('Got stop command')
        if not self.is_running:
            self._logger.info('Camera was not running, name: '+self.name)
            return
        self._do_stop()
        with self.lock:
            self._image_data = None
            self._image_timestamp = None
            self._average_frame_time = None
            self._got_image_event.clear()
        self._logger.info('Acquisition stopped, name: '+self.name)

    @abc.abstractmethod
    def _do_stop(self):
        pass

    def get_next_image(self, timeout=10):
        """Get the next image to be completed. Camera does not have to be running.

        Args:
            timeout (float): Maximum time (seconds) to wait for the image before raising TimeoutError.

        Returns:
            numpy.ndarray: 2d array with image data.
        """
        self._logger.debug('Got next image request')
        assert self.is_init, 'Camera must be initialised'
        if not self.is_running:
            self._logger.debug('Camera was not running, start and grab the first image')
            self._got_image_event.clear()
            self.start()
            if not self._got_image_event.wait(timeout):
                raise TimeoutError('Getting image timed out')
            with self.lock:
                img = self._image_data
            self.stop()
        else:
            self._logger.debug('Camera running, grab the first image to show up')
            self._got_image_event.clear()
            if not self._got_image_event.wait(timeout):
                raise TimeoutError('Getting image timed out')
            with self.lock:
                img = self._image_data
        return img

    def get_new_image(self, timeout=10):
        """Get an image guaranteed to be started *after* calling this method. Camera does not have to be running.

        Args:
            timeout (float): Maximum time (seconds) to wait for the image before raising TimeoutError.

        Returns:
            numpy.ndarray: 2d array with image data.
        """
        self._logger.debug('Got next image request')
        assert self.is_init, 'Camera must be initialised'
        if not self.is_running:
            self._logger.debug('Camera was not running, start and grab the first image')
            self._got_image_event.clear()
            self.start()
            if not self._got_image_event.wait(timeout):
                raise TimeoutError('Getting image timed out')
            with self.lock:
                img = self._image_data
            self.stop()
        else:
            self._logger.debug('Camera running, grab the second image to show up')
            self._got_image_event.clear()
            if not self._got_image_event.wait(timeout/2):
                raise TimeoutError('Getting image timed out')
            self._got_image_event.clear()
            if not self._got_image_event.wait(timeout/2):
                raise TimeoutError('Getting image timed out')
            with self.lock:
                img = self._image_data
        return img

    def get_latest_image(self):
        """Get latest image in the cache immediately. Camera must be running.

        Returns:
            numpy.ndarray: 2d array with image data.
        """
        #self._logger.debug('Got latest image request')
        assert self.is_running, 'Camera must be running'
        with self.lock:
            return self._image_data

    def simple_image_processing(self, img, soft_ops={'flip_x', 'flip_y',
                                                     'rotate_90'}):
        if 'flip_x' in soft_ops and self.flip_x:
            img = np.fliplr(img)
        if 'flip_y' in soft_ops and self.flip_y:
            img = np.flipud(img)
        if 'rotate_90' in soft_ops and self.rotate_90:
            img = np.rot90(img, self.rotate_90)
        return img

    def new_image_frame(self, img):
        """Called by camera implementations in their acquisition thread to
        make new camera frames available.

        This function also computes an average frame rate to be returned by the
        readonly frame_rate_actual property.
        """
        if img is None:
            return
        with self.lock:
            self._image_data = img
            img_ts = self._image_timestamp = datetime.now(UTC)
            last_pts = self._image_precision_timestamp
            self._image_precision_timestamp = precision_timestamp()
            self._imgs_since_start += 1

            if last_pts is not None:
                new_frame_time = self._image_precision_timestamp - last_pts
                if self._average_frame_time is None:
                    self._average_frame_time = new_frame_time
                else:
                    # computing a simple exponential average
                    self._average_frame_time = \
                      .8*self._average_frame_time + .2*new_frame_time

            # copy current set of callbacks for handling below
            callbacks = self._call_on_image.copy()

        self._logger.debug('Image event!')
        self._got_image_event.set()
        self._logger.debug('Time: %s Size:%s Type:%s',
                           img_ts, img.shape, img.dtype)

        # Signal image ready and run callbacks:
        for func in callbacks:
            try:
                #self._logger.debug('Calling back to: %s', func)
                func(img, img_ts)
            except:
                self._logger.warning('Failed image callback "%s"', func,
                                     exc_info=True)


class ColorCapableCamera(Camera):
    available_properties = Camera.available_properties + ('color_bin',)

    def __init__(self, *a, **kw):
        """Abstract base class constructor for color capable cameras."""
        # Downscale when debayering instead of interpolating for speed:
        self._color_bin = True
        super().__init__(*a, **kw)

    @abc.abstractproperty
    def is_color_camera(self):
        pass

    @property
    def color_bin(self):
        """bool: Get or set if colour binning is active.

        Defaults to True for colour cameras. Is always False for mono cameras.

        When colour binning is True, each 2x2 Bayer group on the image sensor will form one RGB pixel in the output.
        If set to False, interpolation will be used to create an RGB image at full resolution. Interpolation may slow
        down the image processing significantly.
        """
        assert self.is_init, 'Camera must be initialised'
        return self.is_color_camera and self._color_bin
    @color_bin.setter
    def color_bin(self, bin):
        self._logger.debug('Set color bin called with: %s', bin)
        assert self.is_init, 'Camera must be initialised'
        bin = bool(bin)
        # only disallow setting color-binning requested and not color camera
        assert (not bin) or self.is_color_camera, \
          'Must have colour camera to do colour binning'
        self._color_bin = bin
        self._logger.debug('Set color bin to: %s', bin)

    @property
    def size_max(self):
        """tuple of int: Get the maximum allowed readout size (width, height) in
        pixels.
        """
        assert self.is_init, 'Camera must be initialised'
        width, height = self._get_raw_size_max()
        return (width, height) if not self.color_bin else (width//2, height//2)

    @abc.abstractmethod
    def _get_raw_size_max(self):
        pass

    def _get_size_readout(self):
        width, height = self._get_raw_size_readout()
        return (width, height) if not self.color_bin else (width//2, height//2)

    @abc.abstractmethod
    def _get_raw_size_readout(self):
        pass

    def _set_size_readout(self, size):
        if self.color_bin:
            size = tuple([x*2 for x in size])
            self._logger.debug('Size adjusted to %s for color binning', size)
        self._set_raw_size_readout(size)

    @abc.abstractmethod
    def _set_raw_size_readout(self, size):
        pass

    
    @Camera.plate_scale.getter
    def plate_scale(self):
        return self().plate_scale * (1 if not self.color_bin else 2)

    def simple_image_processing(self, img, soft_ops={'flip_x', 'flip_y',
                                                     'rotate_90', 'grb_to_rgb',
                                                     'debayer'},
                                color_pattern='RGGB'):
        img = super().simple_image_processing(img, soft_ops = soft_ops)

        if 'grb_to_rgb' in soft_ops and len(img.shape) == 3:
            assert self.is_color_camera, \
                'Invalid Image dimensions for non-color camera'
            # Camera gives GRB, reverse to RGB
            img = img[:, :, ::-1]

        # If color camera we may need to debayer
        if self.is_color_camera and len(img.shape) < 3:
            t0_debayer = precision_timestamp()
            img = debayer_image(
              img, order=color_pattern, downsize=self.parent.color_bin)
            t_debayer = precision_timestamp() - t0_debayer
            debug('Debayered image in %s seconds', t_debayer)

        return img
