"""
Supported Hardware
==================

Pypogs requires a supported mount and camera(s) to function.  Optionally, Pypogs
can facilitate data acquisition using receiver hardware in conjunction with
mount motion and orbit tracking.  Various hardware and software implementations
for mounts, cameras, and recievers are supported in Pypogs, providing for
application to a variety of configurations for sky observations.

As noted below, specific hardware implementations are not meant to be
instantiated directly, but rather through the :func:`pypogs.Hardware.factory`
function that should be used as :func:`pypogs.Mount.factory`,
:func:`pypogs.Camera.factory`, or :func:`pypogs.Receiver.factory`.  This
factory interface facilities better abstraction of the different hardware
implementations and allows for isolating specific software requirements between
the different implementations.

Mounts
------

Current hardware support:
    - :class:`pypogs.Mount`: 'Celestron' for Celestron, Orion and SkyWatcher
      telescopes (using NexStar serial protocol). No additional packages
      required. Tested with Celestron model CPC800.
    - :class:`pypogs.Mount`: 'iOptron AZMP' for iOptron AZMP telescopes. No
      additional packages required.
    - :class:`pypogs.Mount`: 'ASCOM' for ASCOM-enabled mounts. Requires ASCOM
      platform and mount driver.
    - :class:`pypogs.Mount`: 'INDI' for INDI-enabled mounts. Requires INDI
      library and working INDI server.
    - :class:`pypogs.Mount`: 'dummy' for a dummy mounts, mostly to test with.

Mount implementations are not intended to be imported or instantiated directly,
but rather through the :meth:`pypogs.Mount.factory` class method.


Cameras
-------

Current hardware support:
    - :class:`pypogs.Camera`: 'ptgrey' for Point-Grey (bought by FLIR, bought by
      Teledyne) cameras that are supported by the vendor's Spinnaker library
      with Pythpon interface.  Spinnaker and related Python interface is
      required.
    - :class:`pypogs.Camera`: 'zwoasi' for ZWO ASI cameras.
    - :class:`pypogs.Camera`: 'ascom' for ASCOM-supported cameras.  Requires
      ASCOM platform and camera driver.
    - :class:`pypogs.Camera`: 'INDI' for INDI-supported cameras.  Requires INDI
      library and working INDI server with appropriate INDI drivers for at least
      some camera.
    - :class:`pypogs.Camera`: 'aravis' for Aravis-supported USB-Vision or
      GigE-Vision cameras.  Requires Aravis >= v0.8 to be installed.

Mount implementations are not intended to be imported or instantiated directly,
but rather through the :meth:`pypogs.Camera.factory` class method.

Receivers
---------
Pypogs supports receiver hardware that can be used to collect data.

Current hardware support:
    - :class:`pypogs.Receiver`: 'ni_daq' for analog input NIDAQmx-supported
      hardware from National Instruments.
    - :class:`pypogs.Receiver`: 'dummy' for a dummy receiver, mostly to test
      with.

Mount implementations are not intended to be imported or instantiated directly,
but rather through the :meth:`pypogs.Receiver.factory` class method.

This is Free and Open-Source Software originally written by Gustav Pettersson at ESA.

License:
    Copyright 2019 the European Space Agency

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        https://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
"""

from .camera.base import Camera
from .mount.base import Mount
from .receiver.base import Receiver
from .base import Hardware

__all__ = ['Camera', 'Mount', 'Receiver', 'Hardware']

from . import factory
