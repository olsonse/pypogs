import requests

GP_PHP = 'https://celestrak.org/NORAD/elements/gp.php'

def fetch_tle_from_celestrak(norad_cat_id, verify=True, timeout=20):
    '''
    Returns the TLE for a given norad_cat_id as currently available from CelesTrak.
    Raises IndexError if no data is available for the given norad_cat_id.

    Parameters
    ----------
    norad_cat_id : string
        Satellite Catalog Number (5-digit)
    verify : boolean or string, optional
        Either a boolean, in which case it controls whether we verify
        the server's TLS certificate, or a string, in which case it must be a path
        to a CA bundle to use. Defaults to ``True``. (from python-requests)
    timeout=20

    While the future is to replace this function with something that downloads
    and parses OMM files, this function is currently borrowed from the
    satellite_tle package with this license:

    The MIT License (MIT)

    Copyright (c) 2014 Sean Herron, 2018 Fabian P. Schmidt

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
    THE SOFTWARE.
    '''

    r = requests.get(f'{GP_PHP}?CATNR={norad_cat_id}&FORMAT=TLE', verify=verify,
                     timeout=timeout)
    r.raise_for_status()

    if r.text == 'No GP data found':
        raise LookupError

    tle = r.text.split('\r\n')

    return tle[0].strip(), tle[1].strip(), tle[2].strip()
