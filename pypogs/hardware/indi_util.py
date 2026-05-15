# vim: ts=4:sw=4:tw=80:nowrap
"""
Some generic tools useful for interacting with INDI devices.
"""

import re

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
