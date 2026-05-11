"""
Implementation of a pointgrey/FLIR camera as supported by the Spinnaker library.
"""

from datetime import datetime
from time import perf_counter as precision_timestamp
import numpy as np
import PySpin

from . import base

class Camera(base.Camera):
    available_properties = base.Camera.available_properties + (
      'gain', 'frame_rate', 'gain_auto', 'frame_rate_auto',
      'exposure_time_auto',
    )

    def __init__(self, *a, **kw):
        self._ptgrey_camera = None
        self._ptgrey_camlist = None
        self._ptgrey_system = None
        super().__init__(*a, **kw)

    def _deinitialize(self):
        self._logger.debug('Deinitialising PtGrey camera')
        try:
            self._ptgrey_camera.UnregisterEventHandler(self._ptgrey_event_handler)
            self._logger.debug('Unregistered event handler')
        except:
            self._logger.exception('Failed to unregister event handler')
        try:
            self._ptgrey_camera.DeInit()
            del(self._ptgrey_camera)
            self._ptgrey_camera = None
            self._logger.debug('Deinitialised PtGrey camera object and deleted')
        except:
            self._logger.exception('Failed to close task')
        self._logger.debug('Trying to release PtGrey hardware resources')
        self._ptgrey_release()

    def _ptgrey_release(self):
        """Release Point Grey hardware resources."""
        self._logger.debug('PointGrey hardware release called')
        if self._ptgrey_camera is not None:
            self._logger.debug('Deleting PtGrey camera object')
            del(self._ptgrey_camera) #Preferred over =None according to PtGrey
            self._ptgrey_camera = None
        if self._ptgrey_camlist is not None:
            self._logger.debug('Clearing and deleting PtGrey camlist')
            self._ptgrey_camlist.Clear()
            del(self._ptgrey_camlist)
            self._ptgrey_camlist = None
        if self._ptgrey_system is not None:
            self._logger.debug('Has PtGrey system. Is in use? '+str(self._ptgrey_system.IsInUse()))
            if not self._ptgrey_system.IsInUse():
                self._logger.debug('Not in use, releasing and deleting')
                self._ptgrey_system.ReleaseInstance()
                del(self._ptgrey_system)
                self._ptgrey_system = None
        self._logger.debug('Hardware released')

    def set_identity(self, identity):
        self._logger.debug('Using PtGrey, checking vailidity')
        if not self._ptgrey_system:
            self._ptgrey_system = PySpin.System.GetInstance() #Get singleton
        self._ptgrey_camlist = self._ptgrey_system.GetCameras()
        self._logger.debug('Got cam list, size: %d', self._ptgrey_camlist.GetSize())
        self._ptgrey_camera = self._ptgrey_camlist.GetBySerial(identity)
        valid = self._ptgrey_camera.IsValid()
        self._logger.debug('Got object, valid: %s', valid)
        if valid:
            self._logger.debug('Already init?: %s',
              self._ptgrey_camera.IsInitialized())
        if not valid:
            self._logger.debug('Invalid camera object. Cleaning up')
            del(self._ptgrey_camera)
            self._ptgrey_camera = None
            self._ptgrey_camlist.Clear()
            raise AssertionError('Camera %s was not found', identity)
        elif self._ptgrey_camera.IsInitialized():
            self._logger.debug('Camera object already in use. Cleaning up')
            del(self._ptgrey_camera)
            self._ptgrey_camera = None
            self._ptgrey_camlist.Clear()
            raise RuntimeError('The camera is already in use')
        else:
            self._logger.debug('Seems valid. Setting identity and cleaning up')
            del(self._ptgrey_camera)
            self._ptgrey_camera = None
            self._identity = identity
            self._ptgrey_camlist.Clear()

    @property
    def is_init(self):
        return self._ptgrey_camera is not None and \
               self._ptgrey_camera.IsInitialized()

    def _initialize(self):
        assert self.identity is not None, \
          'Must define identity of Pt Grey camera before initialising'
        self._logger.debug('Using PySpin, try to initialise')
        if self._ptgrey_camera is not None:
            raise RuntimeError('There is already a camera object here')
        if not self._ptgrey_system:
            self._ptgrey_system = PySpin.System.GetInstance() #Get singleton
        if self._ptgrey_camlist: #Clear old list and get fresh one
            self._ptgrey_camlist.Clear()
            del(self._ptgrey_camlist)
        self._ptgrey_camlist = self._ptgrey_system.GetCameras()
        self._logger.debug('Getting pyspin object and initialising')
        self._ptgrey_camera = self._ptgrey_camlist.GetBySerial(self.identity)
        self._ptgrey_camera.Init()
        # BASIC SETUP
        self._logger.debug('Setting pixel format to mono16')
        self._ptgrey_camera.PixelFormat.SetValue(PySpin.PixelFormat_Mono16)
        self._logger.debug('Setting gamma off')
        nodemap = self._ptgrey_camera.GetNodeMap()
        PySpin.CBooleanPtr(nodemap.GetNode('GammaEnable')).SetValue(False)
        self._logger.debug('Setting acquisition mode to continuous')
        self._ptgrey_camera.AcquisitionMode.SetIntValue(
          PySpin.AcquisitionMode_Continuous)
        self._logger.debug('Setting stream mode to newest only')
        self._ptgrey_camera.TLStream.StreamBufferHandlingMode.SetIntValue(
          PySpin.StreamBufferHandlingMode_NewestOnly)


        self._ptgrey_event_handler = PtGreyEventHandler(self)
        self._logger.debug('Created ptgrey image event handler')
        self._ptgrey_camera.RegisterEventHandler(self._ptgrey_event_handler)
        self._logger.debug('Registered ptgrey image event handler')
        self._logger.info('Camera successfully initialised')

    @property
    def frame_rate_auto(self):
        """bool: Get or set automatic frame rate.

        If True camera will run as fast as possible.
        """
        self._logger.debug('Get frame rate auto called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CBooleanPtr(nodemap.GetNode('AcquisitionFrameRateEnable'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetValue()
            self._logger.debug('Returning not '+str(val))
            return not val
    @frame_rate_auto.setter
    def frame_rate_auto(self, auto):
        self._logger.debug('Set frame rate called with: '+str(auto))
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CBooleanPtr(nodemap.GetNode('AcquisitionFrameRateEnable'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable. '
                               'Available: %s Writable: %s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting frame rate')
            node.SetValue(not auto)

    @property
    def frame_rate_limit(self):
        """tuple of float: Get the minimum and maximum frame rate in Hz supported."""
        self._logger.debug('Get frame rate limit called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node1 = PySpin.CFloatPtr(nodemap.GetNode('FrameRateHz_Min'))
        node2 = PySpin.CFloatPtr(nodemap.GetNode('FrameRateHz_Max'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node1) or not PySpin.IsAvailable(node2):
            self._logger.debug('One node not available. Node1: %s Node2: %s',
                               PySpin.IsAvailable(node1),
                               PySpin.IsAvailable(node2))
            raise RuntimeError('Unable to read from camera')
        else:
            val = (node1.GetValue(), node2.GetValue())
            self._logger.debug('Returning %s', val)
            return val

    @property
    def frame_rate(self):
        """float: Get or set the camera frame rate in Hz. Will set auto frame rate to False."""
        self._logger.debug('Get frame rate called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('AcquisitionFrameRate'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetValue()
            self._logger.debug('Returning %s', val)
            return val
    @frame_rate.setter
    def frame_rate(self, frame_rate_hz):
        self._logger.debug('Set frame rate called with: '+str(frame_rate_hz))
        assert self.is_init, 'Camera must be initialised'
        frame_rate_hz = float(frame_rate_hz)
        if self.frame_rate_auto:
            self._logger.debug('Frame rate is set to auto. Command auto off')
            self.frame_rate_auto = False
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('AcquisitionFrameRate'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable.  '
                               'Available:%s Writable:%s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting frame rate')
            try:
                node.SetValue(frame_rate_hz)
            except PySpin.SpinnakerException as e:
                if 'OutOfRangeException' in e.message:
                    raise AssertionError(
                      'The commanded value is outside the allowed range. '
                      'See frame_rate_limit')
                else:
                    raise #Rethrows error

    @property
    def gain_auto(self):
        """bool: Get or set automatic gain. If True the gain will be continuously updated."""
        self._logger.debug('Get gain auto called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CEnumerationPtr(nodemap.GetNode('GainAuto'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetCurrentEntry()
            val = val.GetDisplayName().lower()
            self._logger.debug('Node value: '+str(val))
            if val == 'off':
                self._logger.debug('Returning False')
                return False
            elif val == 'continuous':
                self._logger.debug('Returning True')
                return True
            else:
                self._logger.debug('Unexpected return value')
                raise RuntimeError('Unknow response from camera')
    @gain_auto.setter
    def gain_auto(self, auto):
        self._logger.debug('Set gain called with: '+str(auto))
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if auto:
            set_to = 'Continuous'
        else:
            set_to = 'Off'
        self._logger.debug('Will set gain auto to: '+set_to)
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CEnumerationPtr(nodemap.GetNode('GainAuto'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable. '
                               'Available:%s Writable:%s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting gain')
            node.SetIntValue(node.GetEntryByName(set_to).GetValue())

    @property
    def gain_limit(self):
        """tuple of float: Get the minimum and maximum gain supported in the camera's native unit."""
        self._logger.debug('Get gain limit called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node1 = PySpin.CFloatPtr(nodemap.GetNode('GainDB_Min'))
        node2 = PySpin.CFloatPtr(nodemap.GetNode('GainDB_Max'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node1) or not PySpin.IsAvailable(node2):
            self._logger.debug('One node not available. Node1:%s Node2:%s',
                               PySpin.IsAvailable(node1),
                               PySpin.IsAvailable(node2))
            raise RuntimeError('Unable to read from camera')
        else:
            val = (node1.GetValue(), node2.GetValue())
            self._logger.debug('Returning %s', val)
            return val

    @property
    def gain(self):
        """float: Get or set the camera gain in the camera's native unit."""
        self._logger.debug('Get gain called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('Gain'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetValue()
            self._logger.debug('Returning %s', val)
            return val
    @gain.setter
    def gain(self, gain):
        self._logger.debug('Set gain called with: %s', gain)
        assert self.is_init, 'Camera must be initialised'
        if self.gain_auto:
            self._logger.debug('Gain is set to auto. Command auto off')
            self.gain_auto = False
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('Gain'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable. '
                               'Available:%s Writable:%s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting gain')
            try:
                node.SetValue(float(gain))
            except PySpin.SpinnakerException as e:
                if 'OutOfRangeException' in e.message:
                    raise AssertionError('The commanded value is outside the '
                                         'allowed range. See gain_limit')
                else:
                    raise #Rethrow error

    @property
    def exposure_time_auto(self):
        """bool: Get or set automatic exposure time.

        If True the exposure time will be continuously updated.
        """
        self._logger.debug('Get exposure time auto called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CEnumerationPtr(nodemap.GetNode('ExposureAuto'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetCurrentEntry()
            val = val.GetDisplayName().lower()
            self._logger.debug('Node value: '+str(val))
            if val == 'off':
                self._logger.debug('Returning False')
                return False
            elif val == 'continuous':
                self._logger.debug('Returning True')
                return True
            else:
                self._logger.debug('Unexpected return value')
                raise RuntimeError('Unknow response from camera')
    @exposure_time_auto.setter
    def exposure_time_auto(self, auto):
        self._logger.debug('Set exposure time auto called with: %s', auto)
        assert self.is_init, 'Camera must be initialised'
        auto = bool(auto)
        if auto:
            set_to = 'Continuous'
        else:
            set_to = 'Off'
        self._logger.debug('Will set exposure auto auto to: %s', set_to)
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CEnumerationPtr(nodemap.GetNode('ExposureAuto'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable. '
                               'Available:%s Writable:%s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting exposure auto to: %s', set_to)
            node.SetIntValue(node.GetEntryByName(set_to).GetValue())

    @property
    def exposure_time_limit(self):
        """tuple of float: Get the minimum and maximum expsure time in ms
        supported.
        """
        self._logger.debug('Get exposure time limit called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node1 = PySpin.CFloatPtr(nodemap.GetNode('ExposureTime_FloatMin'))
        node2 = PySpin.CFloatPtr(nodemap.GetNode('ExposureTime_FloatMax'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node1) or not PySpin.IsAvailable(node2):
            self._logger.debug('One node not available. Node1:%s Node2:%s',
                               PySpin.IsAvailable(node1),
                               PySpin.IsAvailable(node2))
            raise RuntimeError('Unable to read from camera')
        else:
            val = (node1.GetValue()/1000, node2.GetValue()/1000)
            self._logger.debug('Returning '+str(val))
            return val

    @property
    def exposure_time(self):
        """float: Get or set the camera expsure time in ms.

        Will set auto exposure time to False.
        """
        self._logger.debug('Get exposure time called')
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('ExposureTime'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node):
            self._logger.debug('Node not available')
            raise RuntimeError('Unable to read from camera')
        else:
            val = node.GetValue() / 1000 #microseconds used in PtGrey
            self._logger.debug('Returning %s', val)
            return val
    @exposure_time.setter
    def exposure_time(self, exposure_ms):
        self._logger.debug('Set exposure time called with: '+str(exposure_ms))
        assert self.is_init, 'Camera must be initialised'
        exposure_ms = float(exposure_ms)
        if self.exposure_time_auto:
            self._logger.debug('Exposure time is set to auto. Command auto off')
            self.exposure_time_auto = False
        nodemap = self._ptgrey_camera.GetNodeMap()
        node = PySpin.CFloatPtr(nodemap.GetNode('ExposureTime'))
        self._logger.debug('Got the node')
        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            self._logger.debug('Node not available or not writable. '
                               'Available:%s Writable:%s',
                               PySpin.IsAvailable(node),
                               PySpin.IsWritable(node))
            raise RuntimeError('Unable to command camera')
        else:
            self._logger.debug('Setting exposure time to: %g[μs]',
                               exposure_ms*1000)
            try:
                node.SetValue(exposure_ms*1000)
            except PySpin.SpinnakerException as e:
                if 'OutOfRangeException' in e.message:
                    raise AssertionError(
                      'The commanded value is outside the allowed range.'
                      ' See exposure_time_limit')
                else:
                    raise #Rethrows error

    @property
    def size_max(self):
        """tuple of int: Get the maximum allowed readout size (width, height) in
        pixels.

        For at least some of FLIR/Point-Grey cameras, this value considers the
        current binning setting, thus will not equal SensorWidth/SensorHeight.
        """
        assert self.is_init, 'Camera must be initialised'
        nodemap = self._ptgrey_camera.GetNodeMap()
        node_width = PySpin.CIntegerPtr(nodemap.GetNode('WidthMax'))
        node_height = PySpin.CIntegerPtr(nodemap.GetNode('HeightMax'))
        self._logger.debug('Got WidthMax,HeightMax nodes')
        try:
            val_w = node_width.GetValue()
            val_h = node_height.GetValue()
            self._logger.debug('Got WidthMax,HeightMax: %s, %s', val_w, val_h)
            return val_w, val_h
        except PySpin.SpinnakerException:
            self._logger.debug('Failure reading', exc_info=True)
            raise

    def _get_size_readout(self):
        nodemap = self._ptgrey_camera.GetNodeMap()
        node_width = PySpin.CIntegerPtr(nodemap.GetNode('Width'))
        node_height = PySpin.CIntegerPtr(nodemap.GetNode('Height'))
        self._logger.debug('Got Width,Height nodes')
        try:
            val_w = node_width.GetValue()
            val_h = node_height.GetValue()
            self._logger.debug('Got Width,Height: %s, %s', val_w, val_h)
            return val_w, val_h
        except PySpin.SpinnakerException:
            self._logger.debug('Failure reading', exc_info=True)
            raise

    def _set_size_readout(self, size):
        # Changing readout frame size with Spinnaker is more stable if you:
        # 1) Change offsets to zero
        # 2) Adjust frame width/height to desired
        # 3) Change offsets to desired
        nodemap = self._ptgrey_camera.GetNodeMap()
        node_offs_x = PySpin.CIntegerPtr(nodemap.GetNode('OffsetX'))
        node_offs_y = PySpin.CIntegerPtr(nodemap.GetNode('OffsetY'))
        node_width = PySpin.CIntegerPtr(nodemap.GetNode('Width'))
        node_height = PySpin.CIntegerPtr(nodemap.GetNode('Height'))
        self._logger.debug('Got nodes for offset and size')
        try:
            # 1) change offsets to zero
            node_offs_x.SetValue(0)
            node_offs_y.SetValue(0)
            self._logger.debug('Set offsets to zero')
            # 2) adjust frame width/height
            node_width.SetValue(size[0])
            node_height.SetValue(size[1])
            self._logger.debug('Set desired size')
        except PySpin.SpinnakerException as e:
            self._logger.debug('Failure setting', exc_info=True)
            if 'OutOfRangeException' in e.message:
                raise ValueError('Commanded value not allowed.')
            elif 'AccessException' in e.message:
                raise AssertionError('Not allowed to change readout now.')
            else:
                raise #Rethrows error

        self._logger.debug('Attempt to center frame after changing size.')
        max_size = self.size_max
        try:
            #Read what we set before to be sure:
            actual_w = node_width.GetValue()
            actual_h = node_height.GetValue()
        except PySpin.SpinnakerException:
            self._logger.warning('Could not read frame dims', exc_info=True)
            raise

        self._logger.debug('Actual and max, w,h %d x %d, %d x %d',
                           actual_w, actual_h, max_size[0], max_size[1])
        new_offset = (round((max_size[0] - actual_w) / 2),
                      round((max_size[1] - actual_h) / 2))

        # Some rules (it seems) that Flir/point-grey follows, though it would be
        # nice to be able to programmatically find this information):
        # OffsetX/Width appear to need to be on a grid divisiable by 4
        # OffsetY/Height appear to need to be on a grid divisiable by 2
        # These rules are probably camera-specific
        # TODO:  do something to handle these apparent rules

        self._logger.debug('Neccessary offset: %s', new_offset)

        try:
            # 3) Change offsets to desired
            node_offs_x.SetValue(new_offset[0])
            node_offs_y.SetValue(new_offset[1])
        except PySpin.SpinnakerException:
            self._logger.warning('Failure centering readout', exc_info=True)

    def _get_binning(self):
        """int: Number of pixels to bin in each dimension (e.g. 2 gives 2x2
        binning);

        *ptgrey* cameras bin by summing, *zwoasi* cameras bin by averaging.

        Setting will stop and restart camera if running. Will scale size_readout
        to show the same sensor area.
        """
        nodemap = self._ptgrey_camera.GetNodeMap()
        node_horiz = PySpin.CIntegerPtr(nodemap.GetNode('BinningHorizontal'))
        node_vert = PySpin.CIntegerPtr(nodemap.GetNode('BinningVertical'))
        self._logger.debug('Got the nodes')
        try:
            val_horiz = node_horiz.GetValue()
            val_vert = node_vert.GetValue()
            self._logger.debug('Got '+str(val_horiz)+' '+str(val_vert))
            if val_horiz != val_vert:
                self._logger.warning('Horzontal and vertical binning not equal!')
            return val_horiz
        except PySpin.SpinnakerException:
            self._logger.warning('Failed to read', exc_info=True)

    def _set_binning(self, binning):
        initial_size = self.size_readout
        initial_bin = self.binning
        self._logger.debug('Initial binning and sensor readout area: %s, %s',
                           initial_bin, initial_size)
        # Calculate what the new ROI needs to be set to
        bin_scaling = binning/initial_bin
        new_size = [round(sz/bin_scaling) for sz in initial_size]

        nodemap = self._ptgrey_camera.GetNodeMap()
        node_horiz = PySpin.CIntegerPtr(nodemap.GetNode('BinningHorizontal'))
        node_vert = PySpin.CIntegerPtr(nodemap.GetNode('BinningVertical'))
        self._logger.debug('Got the BinningHorizontal/BinningVertical nodes')
        try:
            node_horiz.SetValue(binning)
            node_vert.SetValue(binning)
        except PySpin.SpinnakerException as e:
            self._logger.debug('Failure setting', exc_info=True)
            if 'OutOfRangeException' in e.message:
                raise ValueError('Commanded value not allowed.')
            elif 'AccessException' in e.message:
                raise AssertionError('Not allowed to change binning now.')
            else:
                raise #Rethrows error
        # Correctly set the ROI to adjust for new binning size
        try:
            self.size_readout = new_size
            self._logger.debug('Set new size to: ' + str(self.size_readout))
        except:
            self._logger.warning('Failed to scale readout after binning change', exc_info=True)

    @property
    def is_running(self):
        """bool: True if device is currently acquiring data."""
        if not self.is_init:
            return False
        return self._ptgrey_camera is not None and self._ptgrey_camera.IsStreaming()

    def _do_start(self):
        try:
            self._ptgrey_camera.BeginAcquisition()
        except PySpin.SpinnakerException as e:
            self._logger.debug('Could not start:', exc_info=True)
            if 'already streaming' in e.message:
                self._logger.warning('The camera was already streaming...')
            else:
                raise RuntimeError('Failed to start camera acquisition') from e

    def _do_stop(self):
        self._logger.debug('Using PtGrey')
        try:
            self._ptgrey_camera.EndAcquisition()
        except:
            self._logger.debug('Could not stop:', exc_info=True)
            raise RuntimeError('Failed to stop camera acquisition')


class PtGreyEventHandler(PySpin.ImageEventHandler):
    """Barebones event handler for ptgrey, just pass along the event to
    the Camera class.
    """
    def __init__(self, parent):
        assert parent.model == 'ptgrey', \
          'Trying to attach ptgrey event handler to non ptgrey model'
        super().__init__()
        self.parent = parent

    def OnImageEvent(self, img_ptr):
        """Read out the image and a timestamp, reshape to array, pass to
        parent.
        """
        self.parent._logger.debug(
          'Image event! Unpack and release pointer')
        self.parent._image_timestamp = datetime.utcnow()
        last_timestamp = self.parent._image_precision_timestamp
        self.parent._image_precision_timestamp = precision_timestamp()

        try:
            # be sure to copy the data from Spinnaker to allow easier release
            img = img_ptr.GetData().reshape((img_ptr.GetHeight(),
                                             img_ptr.GetWidth())).copy()
            img = self.parent.simple_image_processing(img)
            self.parent._image_data = img
        except:
            self.parent._logger.warning('Failed to unpack image', exc_info=True)
            self.parent._image_data = None
        finally:
            img_ptr.Release()
        self.parent._got_image_event.set()
        self.parent._logger.debug('Time: %s Size:%s Type:%s',
                                  self.parent._image_timestamp,
                                  self.parent._image_data.shape,
                                  self.parent._image_data.dtype)
        for func in self.parent._call_on_image:
            try:
                #self.parent._logger.debug('Calling back to: %s', func)
                func(self.parent._image_data, self.parent._image_timestamp)
            except:
                self.parent._logger.warning('Failed image callback',
                                            exc_info=True)
        self.parent._imgs_since_start += 1
        if last_timestamp is not None:
            new_frame_time = self.parent._image_precision_timestamp \
                           - last_timestamp
            if self.parent._average_frame_time is None:
                self.parent._average_frame_time = new_frame_time
            else:
                self.parent._average_frame_time = \
                  .8*self.parent._average_frame_time + .2*new_frame_time

        self.parent._logger.debug('Event handler finished.')
