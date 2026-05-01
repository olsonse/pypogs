
import serial
from time import time as timestamp, sleep
import re

from . import base

class Mount(base.Mount):
    """Generic beginning implementation of a serial-connected mount.

    Specific finished implementations should inherit from this class (rather
    than from the base.Mount).

    There are several properties, including baud that can and probably should be
    overridden by child classes.
    """
    baud = 9600
    eol_byte = b'#'

    def __init__(self, *a, **kw):
        self._serial_port = None
        super().__init__(*a, **kw)

    def open(self, timeout=3.5):
        """Opens serial port specified by port_name string."""
        self._logger.debug('Got open serial port with name: %s', self.identity)
        try:
            self._serial_port = serial.Serial(self.identity, self.baud,
                                              timeout=timeout,
                                              write_timeout=timeout)
            self._logger.debug('Successfully opened serial port')
        except serial.SerialException:
            self._logger.waring('Failed to open serial port "%s"',
                                self.identity, exc_info=True)
            raise

    def close(self):
        """Closes serial port."""
        if self._serial_port is not None:
            self._logger.debug('Closing serial port')
            self._serial_port.close()
            self._serial_port = None
            self._logger.debug('Port closed')

    def test_open(self, port_name):
        self._logger.debug('Try to open serial port and confirm model=%s',
                           self.model)
        if port_name.isnumeric():
            port_name = serial_find_port(port_name, logger=self._logger)
        self._logger.debug('Opening serial port: %s', port_name)

        tst = self.port_test
        res = serial_test(port_name, self.baud, tst['command'], nbytes,
                          self._logger)
        if res == None:
            raise ValueError(f'Serial port "{port_name}" test read failed')
        if not re.match(tst['response_regex'], res):
            raise ValueError(f'Serial port "{port_name}" validation failed')
        return port_name

    def set_identity(self, identity):
        identity = self.test_open(identity)
        self._logger.debug('Setting identity to: %s', identity)
        self._identity = identity

    @property
    def serial_is_open(self):
        return self._serial_port != None and self._serial_port.isOpen()

    def send_bytes_command(self, command):
        """Send bytes to mount."""
        assert self.serial_is_open, 'Serial port is not open'
        self._serial_port.write(bytes(command))
        self._serial_port.flush() #Push out data

    def send_text_command(self, command):
        """Encode as ASCII and send to mount."""
        self._serial_port.write(command.encode('ASCII'))
        self._serial_port.flush() #Push out data

    def read_to_eol(self, eol_byte=b'#', timeout=3):
        """Read response to the EOL byte character. Return bytes."""
        assert self.serial_is_open, 'Serial port is not open'
        timeout_time = timestamp() + timeout
        response = b'' #Empty type 'bytes'
        while timestamp() < timeout_time:
            r = self._serial_port.read(1)
            if r == eol_byte:
                return response
            else:
                response += r

            if timestamp() > timeout_time:
                self._logger.info('timed out waiting for serial response '
                                  '(read: "%s", looking for eol byte: %s)',
                                  response, eol_byte)
                return None
            sleep(0.0001) # give the CPU a chance to do something else

    def query_command(self, command, eol_byte=None):
        """Encodes as ASCII and sends command string to mount, then reads and
        returns response string from mount ending in indicated end-of-line
        character.

        inputs:
          command (str):   command message to be sent to mount.
          eol_byte (byte, optional): expected terminating character at end of
            mount response.

        returns:  ASCII string response from mount up to and including EOL byte
          character.
        """
        assert self.serial_is_open, 'Serial port is not open'
        response = b''
        self._logger.debug('Sending serial command "%s" to mount', command)
        try:
            self.clear_buffers()
            self._send_text_command(command)
            response = self.read_to_eol(eol_byte)
            if response is None:
                self._logger.warning('No response from mount (query: "%s")',
                                     command)
                response = b''
        except:
            self._logger.debug('Failed to communicate', exc_info=True)
            raise
        return response


        return serial_query(self._serial_port, command,
                            eol_byte if eol_byte != None else self.eol_byte)

    def check_ack(self, ack_byte = None):
        """Read one byte and compare to the acknowledge byte character."""
        assert self.serial_is_open, 'Serial port is not open'
        ack_byte = ack_byte if ack_byte != None else self.eol_byte
        b = self._serial_port.read()
        return b == ack_byte

    def clear_buffers(self):
        """Clear input and output serial buffers"""
        self._serial_port.reset_input_buffer()
        self._serial_port.reset_output_buffer()

    def _command_stop(self):
        """Tell the mount to stop."""
        self.clear_buffers()
        self.set_rate_alt_az(0,0)

    def _deinitialize(self):
        self._logger.debug('Closing and deleting serial port')
        self.close()


"""
import serial.tools.list_ports
ports = serial.tools.list_ports.comports()
for port in ports:
    print(f"Device: {port.device}, Description: {port.description}")
"""

def list_available_ports():
    """List the available serial port names and descriptions.

    Returns:
        list of tuple: (device, description) for each available serial port (see
        serial.tools.list_ports).
    """
    import serial.tools.list_ports as ports
    return [(x.device, x.description) for x in  ports.comports()]

def serial_find_port(port_index, logger=None):
    """Get serial port name at a given index, starting at zero"""
    port_index = int(port_index)
    if logger:
      logger.debug('Searching for serial port at index: %d', port_index)

    ports = list_available_ports()
    num_ports = len(ports)
    if logger:
      logger.debug('Found %d ports: %d', num_ports, ports)
    assert port_index < num_ports, \
      'Port index %i out of range (%i ports found)' % (port_index, num_ports)
    return ports[port_index][0]


def serial_test(port_name, baud, test_command, nbytes, logger=None):
    """Test if serial communication is established by sending """
    if logger:
        logger.debug('Testing serial port "%s" with test command "%s", '
                      'reading %i bytes', port_name, test_command, nbytes)
        logger.debug('Testing serial port "%s", baud %i', port_name, baud)

    try:
        with serial.Serial(port_name, baud, timeout=3.5, write_timeout=3.5) as ser:
            ser.write(test_command.encode('ASCII'))
            ser.flush()
            response = ser.read(nbytes)
            if logger:
                logger.debug('Got response: %s', response)
            return response
    except serial.SerialException:
        if logger:
            logger.warning('Failed to communicate on serial port %d', port_name,
                           exc_info=True)
        return []
