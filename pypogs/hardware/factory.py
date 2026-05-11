"""
Factory for hardware components.

We use a factory pattern to better separate the different modules until they are
needed.  This allows for easier support of multiple platforms using delayed
module imports.

To instantiate a specific implementation for a piece of hardware, use the
:function:`pypogs.Mount.factory` function from the :class:`pypogs.Mount` class.
"""

__all__ = ['available', 'factory', 'class_to_model']

import importlib

PARENT = 'pypogs.hardware'

available = dict(
  mount = {
    # Type Name       relative module path to implemented class
    'ASCOM'         : 'mount.ascom.Mount',
    'iOptron AZMP'  : 'mount.ioptron.AZMP',
    'Celestron'     : 'mount.celestron.Mount',
    'dummy'         : 'mount.dummy.Mount',
  },

  camera = {
    'ptgrey'        : 'camera.spinnaker.Camera',
    'zwoasi'        : 'camera.zwoasi.Camera',
    'ascom'         : 'camera.ascom.Camera',
  },

  receiver = {
    'ni_daq'        : 'receiver.ni.Receiver',
    'dummy'         : 'receiver.dummy.Receiver',
  },
)

def class_to_model(instance):
    """
    Do a reverse lookup of model instance to model name, such as ASCOM,
    Celestron, etc.
    """
    T = type(instance)
    modpath = f'{T.__module__}.{T.__qualname__}'.partition(PARENT)[-1][1:]
    for k, v in available[instance.type].items():
      if v == modpath:
        return k
    raise KeyError('Invalid hardware class: ' + modpath)

def factory(key, type):
    """Lookup the class type in available hardware types and return a class"""
    if key not in available[type]:
        raise KeyError(f'Could  not identify {type} type {key}')

    module_path, _, classname = available[type][key].rpartition('.')
    m = importlib.import_module('.' + module_path, PARENT)
    if not hasattr(m, classname):
        raise KeyError(f'module "{PARENT}.{module_path}" does not contain '
                       f'class "{classname}"')

    return getattr(m, classname)
