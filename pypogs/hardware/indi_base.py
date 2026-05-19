# vim: ts=4:sw=4:tw=80:nowrap
"""
Generic base Hardware class useful for interacting with INDI devices.

This interface allows for more use of INDI-supported hardware, opening up more
generic access to multiple hardware types.
"""

import abc, time, re
from functools import cached_property
import PyIndi

from . import base

def parse_identity(identity):
    if not identity:
        return None
    m = re.match(r'(^'
                    r'(?P<host>[0-9a-zA-Z]([0-9a-zA-Z-]*[0-9a-zA-Z])?)'
                    r'(:(?P<port>[1-9][0-9]*))?'
                 r'/)?(\'(?P<quoted_device>[^\']+)\'|'
                      r'"(?P<dquoted_device>[^"]+)"|'
                       r'(?P<device>[^:/"\']+))$',
                 identity)
    return m

class Hardware(base.Hardware, abc.ABC, PyIndi.BaseClient):
    """Generic Pypogs interface to INDI-supported hardware

    Care will need to be taken to ensure that PyIndi.BaseClient is kept as the
    last in the inheritance chain because the PyIndi SWIG implementation does
    not correctly call super().__init__().

    Inheriting classes can implement various PyIndi.BaseClient callbacks to get
    property updates:
        def updateProperty(self, p)
        def newProperty(self, p)
        etc. (see PyIndi.BaseClient documentation)
    """

    MAX_ENUMERATION_WAIT = 10 # maximum wait (in seconds) for device updates

    # Inheriting classes can add to this for properties to clear on server
    # (dis)connections.
    CACHED_PROPERTIES = ['device_name']

    def __init__(self, *a, **kw):
        self.device = None
        super().__init__(*a, **kw)

    @abc.abstractproperty
    def REQUIRED_INTERFACE(self):
        """Or'd set of device interfaces that the connected device must support.

        Example:
            REQUIRED_INTERFACE = (
                PyIndi.BaseDevice.TELESCOPE_INTERFACE |
                PyIndi.BaseDevice.GUIDER_INTERFACE
            )

        Child classes define this attribute (either as class or instance
        attribute to ensure that the connected device is of the proper type.
        """
        pass

    def serverConnected(self):
        """PyIndi.BaseClient callback on server connections"""
        self._logger.info('Connected to indi server: %s:%d',
                          self.getHost(), self.getPort())

    def serverDisconnected(self, code):
        """PyIndi.BaseClient callback on server disconnections"""
        self._logger.info('Disconnected from indi server: %s:%d; clear device.',
                          self.getHost(), self.getPort())
        del self.device
        self.device = None
        self.free_cached_properties() # reset cached device name

    def newDevice(self, device):
        """PyIndi.BaseClient callback on new device enumerations"""
        if device.getDeviceName() == self.device_name:
            self.device = device
        self.free_cached_properties()

    def open_device(self, identity = None):
        """
        Open connection to server and test if this is a telescope mount.

        Returns SWIG proxy/handle to telescope device.
        """
        old_identity = self.identity
        identity = identity if identity else self.identity
        parsed = self.parse_identity(identity)
        if not parsed:
            raise ValueError(f'INDI:  invalid INDI mount "{identity}"; '
                             'expected [HOST[:PORT]/]MOUNT')
        host, port, device = parsed

        self.setServer(host, int(port))
        try:
            self._identity = identity
            if not self.connectServer():
                return False

            tf = time.time() + self.MAX_ENUMERATION_WAIT
            while (not self.device) and time.time() <= tf:
                time.sleep(0.1)
            good = (bool(self.device) and
                ((self.device.getDriverInterface() & self.REQUIRED_INTERFACE)
                     == self.REQUIRED_INTERFACE)
            )
            # TODO: implement more checks to see if the device has enough
            # capability for pypogs
            return good
        except:
            self._identity = old_identity
            self.setServer(old_host, old_port)

    def close(self):
        self.disconnectServer()

    def free_cached_properties(self):
        """Automatically called on new connetions and disconnections"""
        # clear all
        for attr in self.CACHED_PROPERTIES:
            try: delattr(self, attr)
            except: pass

    def set_identity(self, identity):
        try:
            if not self.open_device(identity):
                raise ValueError(
                  f'INDI:  Could not connect to INDI mount "{identity}"; ')
        finally:
            self.close()

    def parse_identity(self, identity):
        if not identity:
            return None
        m = parse_identity(identity)
        if not m:
            return None
        old_host, old_port = self.getHost(), self.getPort()
        host = m['host'] or old_host
        port = m['port'] or old_port
        device = m['quoted_device'] or m['dquoted_device'] or m['device']
        return host, port, device

    @cached_property
    def device_name(self):
        parsed = self.parse_identity(self.identity)
        if not parsed:
            return ''
        return parsed[-1]

    def getProperty(self, type, name):
        """Attempt to wait for INDI server to send properties to client"""
        getfun = getattr(self.device, 'get' + type)
        prop = None
        tf = time.time() + 4 * self.polling_period # quite permissive in time
        while not prop and time.time() <= tf:
            time.sleep(0.01)
            prop = getfun(name)
        if not prop:
            raise RuntimeError(f'Could not get INDI {type}: "{name}"')
        return prop

    @property
    def polling_period(self):
        """Returns the INDI polling period (in seconds) for the main device"""
        # for polling period, we will wait at least as long as enumeration time
        tf = time.time() + self.MAX_ENUMERATION_WAIT
        pp = None
        while not pp and time.time() <= tf:
            time.sleep(0.01)
            pp = self.device.getNumber('POLLING_PERIOD')
        S = {pi.getName().lower():pi.getValue() for pi in pp}
        return S.get('period_ms', 1000) / 1000.0

    def _initialize(self):
        self.watchDevice(self.device_name)

        if not self.open_device():
            self.close()
            raise RuntimeError(f'Could not open INDI device: "{self.identity}"')

    _deinitialize = close
