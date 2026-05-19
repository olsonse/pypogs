# vim: ts=4:sw=4:tw=80:nowrap
"""
INDI implementation of a camera.

This interface allows for more use of INDI-supported hardware, opening up more
generic access to mount hardware.
"""

from functools import cached_property
from time import perf_counter as precision_timestamp
import numpy as np
import astropy.io.fits
import PyIndi

from . import base
from .. import indi_base

try:
    import cv2
except:
    cv2 = None

# be sure to keep PyIndi.BaseClient as the last in the inheritance chain because
# the PyIndi SWIG implementation does not correctly call super().__init__().
class Camera(base.Camera, indi_base.Hardware):
    """Pypogs interface to an INDI-supported camera.

    Identity is specified as:
      [HOST[:PORT]/]CAMERA

        CAMERA may be quoted for INDI device names including : and / characters.

    where
      HOST : hostname of remote INDI server (defaults to localhost).
      PORT : TCP port of remote INDI server (defaults to 7624).
      CAMERA: Name of Camera interface on remote INDI server.
    """
    available_properties = base.Camera.available_properties + ('gain',
      'roi_increments',
    )

    CACHED_PROPERTIES = indi_base.Hardware.CACHED_PROPERTIES + [
      'gain_property', 'binning_property', 'exposure_property', 'ccd_info',
      'ccd1_blob', 'ccd_frame_property', 'ccd_frame',
      'ccd_stream_frame_property', 'ccd_stream_frame',
      'ccd_video_stream_property',
    ]

    REQUIRED_INTERFACE = PyIndi.BaseDevice.CCD_INTERFACE

    BLOB_MODES = {
        #PyIndi.B_ONLY : 'ignore-other', # not going to use B_ONLY
        PyIndi.B_ALSO : 'on',
        PyIndi.B_NEVER: 'off',
    }

    def __init__(self, *a, **kw):
        self._roi_increments = dict(x=1, y=1, width=1, height=1)
        self.stream_depth = None
        super().__init__(*a, **kw)

    def _initialize(self):
        super()._initialize()
        self.ccd1_blob_mode = 'off'

    @cached_property
    def binning_property(self):
        return self.getProperty('Number', 'CCD_BINNING')

    def _get_binning(self):
        """int: Number of pixels to bin in each dimension (e.g. 2 gives 2x2
        binning);

        Setting will stop and restart camera if running. Will scale size_readout
        to show the same sensor area.
        """
        bx = self.binning_property[0].getValue()
        by = self.binning_property[1].getValue()
        if bx != by:
            self._logger.warning('Horizontal & vertical binning not equal!')
        return bx

    def _set_binning(self, binning):
        """Keep effective region of interest constant while changing binning."""
        if not isinstance(binning, int):
            raise ValueError(f'INDI: binning needs to be integer: "{binning}"')
        self.binning_property[0].setValue(binning)
        self.binning_property[1].setValue(binning)
        self.sendNewNumber(self.binning_property)

    @cached_property
    def exposure_property(self):
        return self.getProperty('Number', 'CCD_EXPOSURE')

    @property
    def exposure_time_limit(self):
        """tuple of float: Get the minimum and maximum expsure time in ms
        supported.
        """
        return (self.exposure_property[0].getMin() * 1000,
                self.exposure_property[0].getMax() * 1000)

    @property
    def exposure_time(self):
        """float: Get or set the camera expsure time in ms.

        Will set auto exposure time to False.
        """
        return self.exposure_property[0].getValue() * 1000
    @exposure_time.setter
    def exposure_time(self, exposure_ms):
        self._logger.debug('Set exposure time called with: %s', exposure_ms)
        assert self.is_init, 'Camera must be initialised'
        self.exposure_property[0].setValue(float(exposure_ms) / 1000.0)
        self.sendNewNumber(self.exposure_property)

    @cached_property
    def gain_property(self):
        return self.getProperty('Number', 'CCD_GAIN')

    @property
    def gain(self):
        """The enable tracking switch."""
        return self.gain_property[0].getValue()
    @gain.setter
    def gain(self, value):
        self.gain_property[0].setValue(float(value))
        self.sendNewNumber(self.gain_property)

    @property
    def gain_limit(self):
        """tuple of float: Get the minimum and maximum gain supported in the
        camera's native unit.
        """
        return self.gain_property[0].getMin(), self.gain_property[0].getMax()

    @cached_property
    def ccd_info(self):
        p = self.getProperty('Number', 'CCD_INFO')
        return {i.getName():i.getValue() for i in p}

    @property
    def size_max(self):
        return self.ccd_info['CCD_MAX_X'], self.ccd_info['CCD_MAX_Y']

    @cached_property
    def ccd1_blob(self):
        return self.getProperty('BLOB', 'CCD1')

    @property
    def ccd1_blob_mode(self):
        return self.BLOB_MODES[self.getBLOBMode(self.device_name, 'CCD1')]
    @ccd1_blob_mode.setter
    def ccd1_blob_mode(self, value):
        r_blob_modes = {v:k for k, v in self.BLOB_MODES.items()}
        assert value in r_blob_modes, 'Unexpected ccd1 blob mode "{value}"'
        return self.setBLOBMode(r_blob_modes[value], self.device_name, 'CCD1')

    @cached_property
    def ccd_frame_property(self):
        return self.getProperty('Number', 'CCD_FRAME')

    @cached_property
    def ccd_frame(self):
        return {i.getName():i for i in self.ccd_frame_property}

    def _get_size_readout(self):
        return (self.ccd_frame['WIDTH'].getValue(),
                self.ccd_frame['HEIGHT'].getValue())

    @cached_property
    def ccd_stream_frame_property(self):
        return self.getProperty('Number', 'CCD_STREAM_FRAME')

    @cached_property
    def ccd_stream_frame(self):
        return {i.getName():i for i in self.ccd_stream_frame_property}

    @cached_property
    def ccd_video_stream_property(self):
        return self.getProperty('Switch', 'CCD_VIDEO_STREAM')

    @property
    def streaming(self):
        S = {i.getName():i.getState() for i in self.ccd_video_stream_property}
        return S['STREAM_ON'] == PyIndi.ISS_ON
    @streaming.setter
    def streaming(self, value):
        self.ccd_video_stream_property.reset()
        S = {i.getName():i for i in self.ccd_video_stream_property}
        S['STREAM_ON'].setState(PyIndi.ISS_ON if value else PyIndi.ISS_OFF)
        S['STREAM_OFF'].setState(PyIndi.ISS_OFF if value else PyIndi.ISS_ON)
        self.sendNewSwitch(self.ccd_video_stream_property)

    @property
    def roi_increments(self):
        return self._roi_increments
    @roi_increments.setter
    def roi_increments(self, value):
        assert isinstance(value, dict) and \
            {'x','y', 'width', 'height'}.issubset(value), \
          'ROI Increments must be set as dictionary of x, y, width, height.'

    def _set_size_readout(self, size):
        """Sets frame for both streaming and exposures to be the same."""
        wi = self.roi_increments['width']
        hi = self.roi_increments['height']
        xi = self.roi_increments['x']
        yi = self.roi_increments['y']

        size = [round(size[0] / wi) * wi, round(size[1] / hi) * hi]
        max_size = self.size_max
        offs = [round((max_size[0] - size[0]) / 2),
                round((max_size[1] - size[1]) / 2)]
        offs = [round(offs[0] / xi) * xi, round(offs[1] / yi) * yi]

        self.ccd_frame['X'].setValue(offs[0])
        self.ccd_frame['Y'].setValue(offs[1])
        self.ccd_frame['WIDTH'].setValue(size[0])
        self.ccd_frame['HEIGHT'].setValue(size[1])

        self.ccd_stream_frame['X'].setValue(offs[0])
        self.ccd_stream_frame['Y'].setValue(offs[1])
        self.ccd_stream_frame['WIDTH'].setValue(size[0])
        self.ccd_stream_frame['HEIGHT'].setValue(size[1])
        self.sendNewNumber(self.ccd_frame_property)
        self.sendNewNumber(self.ccd_stream_frame_property)

    @property
    def is_running(self):
        """bool: True if device is currently acquiring data."""
        if not self.is_init:
            return False
        return bool(self.device) and self.ccd1_blob_mode != 'off'

    def _do_start(self):
        self.ccd1_blob_mode = 'on'
        self.streaming = True

    def _do_stop(self):
        self.streaming = False
        self.ccd1_blob_mode = 'off'

    def updateProperty(self, p):
        """Emmited when new property is created for INDI driver"""
        if p.getDeviceName() != self.device_name:
            return

        if p.getName() == 'STREAM_FULL_DEPTH':
            if p.getType() != PyIndi.INDI_SWITCH:
                self._logger.warning('Wrong STREAM_FULL_DEPTH type')
                return
            sfd = {i.getName():i.getState() for i in p.getSwitch()}
            self.stream_depth = 16 if sfd['FULL_DEPTH_16BIT'] else 8
        elif p.getName() == 'CCD1':
            if p.getType() != PyIndi.INDI_BLOB:
                self._logger.warning('CCD1 expected BLOB type')
                return
            self.handle_image_blob(p.getBLOB())
    newProperty = updateProperty


    def handle_image_blob(self, blob):
        if blob.getState() != PyIndi.IPS_OK:
            self._logger.warning('INDI: Invalid image BLOB received')
            return
        if len(blob) != 1:
            self._logger.warning('INDI: CCD1 expected len(blob) == 1')
            return
        if blob[0].getSize() == 0:
            self._logger.warning('INDI: CCD1 expected some data')
            return

        # get the data and then do something with it
        data = blob[0].getblobdata()
        fmt = blob[0].getFormat()

        # do something with the data depending on the data type
        if fmt == '.stream_jpg':
            # 'MJPEG' stream type set by the stream manager encoder setting
            if cv2 == None:
                self._logger.warning('Cannot decode JPG data without cv2')
                return
            if self.stream_depth != 8:
                self._logger.warning('Cannot decode %d-bit JPG data',
                                     self.stream_depth)
                return
            nd = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(nd, cv2.IMREAD_GRAYSCALE)
        elif fmt == '.stream':
            # raw type of stream, 8bit or 16bit
            dtype = np.uint16 if self.stream_depth == 16 else np.uint8
            img = np.frombuffer(data, dtype=dtype).reshape(
                int(self.ccd_stream_frame['HEIGHT'].getValue()),
                int(self.ccd_stream_frame['WIDTH'].getValue()),
            )
        elif fmt == '.bin':
            # raw type of exposure, 8bit or 16bit
            dtype = np.uint16 if self.stream_depth == 16 else np.uint8
            img = np.frombuffer(data, dtype=dtype).reshape(
                int(self.ccd_frame['HEIGHT'].getValue()),
                int(self.ccd_frame['WIDTH'].getValue()),
            )
        elif fmt == '.fits':
            f = astropy.io.fits.HDUList.fromstring(bytes(data))
            img = f[0].data
        else:
            self._logger.warning('INDI: Cannot decode image format "%s"', fmt)
            return

        self.new_image_frame(self.simple_image_processing(img))
