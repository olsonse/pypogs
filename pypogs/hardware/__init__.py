"""Mount interfaces
======================

Current harware support:
    - :class:`pypogs.Mount`: 'Celestron' for Celestron, Orion and SkyWatcher
      telescopes (using NexStar serial protocol). No additional packages
      required. Tested with Celestron model CPC800.
    - :class:`pypogs.Mount`: 'iOptron AZMP' for iOptron AZMP telescopes. No
      additional packages required.
    - :class:`pypogs.Mount`: 'ASCOM' for ASCOM-enabled mounts. Requires ASCOM
      platform and mount driver.

Mount implementations are not intended to be imported or instantiated directly,
but rather through the :module:`hardware.factory` interface.

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

from .hardware_camera import Camera
from .mount.base import Mount
from .receiver.base import Receiver

__all__ = ['Camera', 'Mount', 'Receiver']

from . import factory
