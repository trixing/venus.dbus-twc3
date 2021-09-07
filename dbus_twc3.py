#!/usr/bin/env python

"""
Created by Jan Dittmer <jdi@l4x.org> in 2021

Losely Based on DbusDummyService and RalfZim/venus.dbus-fronius-smartmeter
"""
try:
  import gobject
except ImportError:
  from gi.repository import GLib as gobject
import platform
import json
import logging
import sys
import os
import requests # for http GET
try:
    import thread   # for daemon = True
except ImportError:
    pass

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../velib_python'))
from vedbus import VeDbusService

log = logging.getLogger("DbusTWC3")

_URL ='http://TeslaWallConnector.local/api/1'
URL = _URL + '/vitals'
LIFETIME = _URL + '/lifetime'
VERSION = _URL + '/version'

class DbusTWC3Service:

  def _version(self):
    r = requests.get(url = VERSION, timeout=10)
    return r.json() 

  def __init__(self, servicename, deviceinstance, productname='Tesla Wall Connector 3', connection='ip'):
    v = self._version()
    self._lifetime()
    self._dbusservice = VeDbusService(servicename)
    paths=[
      '/Ac/Power',
      '/Ac/L1/Power',
      '/Ac/L2/Power',
      '/Ac/L3/Power',
      '/Ac/Energy/Forward',
      '/Ac/Frequency',
      '/Ac/Voltage',
      '/Status',
      '/Current',
      '/MaxCurrent',
      '/Mode',
      '/ChargingTime'
    ]

    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', connection)

    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', 16)
    self._dbusservice.add_path('/ProductName', productname + ' - ' + v['serial_number'])
    self._dbusservice.add_path('/FirmwareVersion', v['firmware_version'])
    self._dbusservice.add_path('/HardwareVersion', v['part_number'])
    self._dbusservice.add_path('/Connected', 1)


    for path in paths:
      self._dbusservice.add_path(path, None)

    self._dbusservice.add_path(
        '/SetCurrent', None, writeable=True, onchangecallback=self._setcurrent)
    self._dbusservice.add_path(
        '/StartStop', None, writeable=True, onchangecallback=self._startstop)

    gobject.timeout_add(5000, self._safe_update)

  def _setcurrent(self, path, value):
      print('Unimplemented', path, value)
      return True

  def _startstop(self, path, value):
      print('Unimplemented', path, value)
      return True

  def _safe_update(self):
    try:
        self._update()
    except Exception as e:
        log.error('Error running update %s' % e)
    return True

  def _lifetime(self):
    r = requests.get(url = LIFETIME, timeout=10)
    # Should really be lt = r.json(), but API is broken
    #lt = json.loads(r.content.replace('nan', 'null').decode(r.encoding))
    lt = json.loads(r.text.replace('nan', 'null'))
    return lt

  def _update(self):
    r = requests.get(url = URL, timeout=10)
    d = r.json() 
    lt = self._lifetime()
    ds = self._dbusservice
    ds['/Ac/L1/Power'] = float(d['currentA_a']) * float(d['voltageA_v'])
    ds['/Ac/L2/Power'] = float(d['currentB_a']) * float(d['voltageB_v'])
    ds['/Ac/L3/Power'] = float(d['currentC_a']) * float(d['voltageC_v'])
    ds['/Ac/Power'] = ds['/Ac/L1/Power'] + ds['/Ac/L2/Power'] + ds['/Ac/L3/Power']
    ds['/Ac/Frequency'] = d['grid_hz']
    ds['/Ac/Voltage'] = d['grid_v']
    ds['/Current'] = d['vehicle_current_a']
    ds['/SetCurrent'] = 16  # static for now
    ds['/MaxCurrent'] = 16  # d['vehicle_current_a']
    # ds['/Ac/Energy/Forward'] = float(d['session_energy_wh']) / 1000.0
    ds['/Ac/Energy/Forward'] = float(lt['energy_wh']) / 1000.0
    ds['/ChargingTime'] = d['session_s']

    state = 0 # disconnected
    if d['vehicle_connected'] == True:
        state = 1 # connected
        if d['vehicle_current_a'] > 1:
            state = 2 # charging
    ds['/Status'] = state
    ds['/Mode'] = 0 # Manual, no control
    ds['/StartStop'] = 1 # Always on
    log.info("Car Consumption: %s, State: %s" % (ds['/Ac/Power'], ds['/Status']))
    return d


def main():
  #logging.basicConfig(level=logging.INFO)

  root = logging.getLogger()
  root.setLevel(logging.INFO)

  handler = logging.StreamHandler(sys.stdout)
  handler.setLevel(logging.INFO)
  formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  handler.setFormatter(formatter)
  root.addHandler(handler)

  log.info('Startup')

  try:
    thread.daemon = True # allow the program to quit
  except NameError:
    pass

  from dbus.mainloop.glib import DBusGMainLoop
  # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
  DBusGMainLoop(set_as_default=True)

  pvac_output = DbusTWC3Service(
    servicename='com.victronenergy.evcharger.twc3',
    deviceinstance=42)

  logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
  mainloop = gobject.MainLoop()
  mainloop.run()

if __name__ == "__main__":
  main()
