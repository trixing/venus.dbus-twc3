#!/usr/bin/env python

"""
Created by Jan Dittmer <jdi@l4x.org> in 2021

Losely Based on DbusDummyService and RalfZim/venus.dbus-fronius-smartmeter
"""
try:
  import gobject
except ImportError:
  from gi.repository import GLib as gobject
import argparse
import platform
import json
import logging
import sys
import os
import requests # for http GET
import time
try:
    import thread   # for daemon = True
except ImportError:
    pass

import dbus

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../velib_python'))
from vedbus import VeDbusService

log = logging.getLogger("DbusTWC3")


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()



class DbusTWC3Service:

  def _version(self):
    r = requests.get(url = self.VERSION, timeout=10)
    return r.json() 

  def __init__(self, servicename, deviceinstance,
               productname='Tesla Wall Connector 3', name='TWC3',
               ip=None,
               dryrun=False):
    self._name = name
    ip = ip or 'TeslaWallConnector.local'
    url = 'http://' + ip + '/api/1'
    self.URL = url + '/vitals'
    self.LIFETIME = url + '/lifetime'
    self.VERSION = url + '/version'
    v = self._version()
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
      '/ChargingTime',
      '/PCB/Temperature',
      '/MCU/Temperature',
      '/Handle/Temperature',
      '/History/ChargingCycles',
      '/History/ConnectorCycles',
      '/History/Ac/Energy/Forward',
      '/History/Uptime',
      '/History/ChargingTime',
      '/History/Alerts',
      '/History/AverageStartupTemperature',
      '/History/AbortedChargingCycles',
      '/History/ThermalFoldbacks'
    ]

    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', ip)

    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', 16)
    self._dbusservice.add_path('/ProductName', productname + ' - ' + v['serial_number'])
    self._dbusservice.add_path('/FirmwareVersion', v['firmware_version'])
    self._dbusservice.add_path('/HardwareVersion', v['part_number'])
    self._dbusservice.add_path('/Connected', 1)

    self._dbusservice.add_path('/CustomName', 'Tesla Charger')


    for path in paths:
      self._dbusservice.add_path(path, None)

    self._dbusservice.add_path(
        '/SetCurrent', None, writeable=True, onchangecallback=self._setcurrent)
    self._dbusservice.add_path(
        '/StartStop', None, writeable=True, onchangecallback=self._startstop)

    self._tempservice = self.add_temp_service(deviceinstance, dryrun)

    self._retries = 0
    self._lifetime()
    gobject.timeout_add(5000, self._safe_update)
    gobject.timeout_add(60000, self._lifetime_update)

  def add_temp_service(self, instance, dryrun):

      ds = VeDbusService('com.victronenergy.temperature.twc3' + ('_dryrun' if dryrun else ''),
                         bus=dbusconnection())
      # Create the management objects, as specified in the ccgx dbus-api document
      ds.add_path('/Mgmt/ProcessName', __file__)
      ds.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
      ds.add_path('/Mgmt/Connection', 'local')

      # Create the mandatory objects
      ds.add_path('/DeviceInstance', instance + (100 if dryrun else 0))
      ds.add_path('/ProductId', 0)
      ds.add_path('/ProductName', 'dbus-twc3')
      ds.add_path('/FirmwareVersion', 0)
      ds.add_path('/HardwareVersion', 0)
      ds.add_path('/Connected', 1)

      ds.add_path('/CustomName', self._name)
      ds.add_path('/TemperatureType', 2)  # 0=battery, 1=fridge, 2=generic
      ds.add_path('/Temperature', 0)
      ds.add_path('/Status', 0)  # 0=ok, 1=disconnected, 2=short circuit
      return ds

  def _setcurrent(self, path, value):
      print('Unimplemented', path, value)
      return True

  def _startstop(self, path, value):
      print('Unimplemented', path, value)
      return True

  def _lifetime_update(self):
    try:
        self._lifetime()
    except Exception as e:
        log.error('Error running lifetime update %s' % e)
    return True

  def _safe_update(self):
    try:
        self._update()
        if self._retries > 0:
            self._dbusservice['/Connected'] = 1
        self._retries = 0
    except Exception as e:
        log.error('Error running update %s' % e)
        if self._retries == 0:
            self._dbusservice['/Connected'] = 0
            self._tempservice['/CustomName'] = self._name + ' Error'
            self._tempservice['/Temperature'] = -1
        self._retries += 1
    return True

  def _lifetime(self):
    r = requests.get(url = self.LIFETIME, timeout=10)
    # Should really be lt = r.json(), but API is broken
    #lt = json.loads(r.content.replace('nan', 'null').decode(r.encoding))
    lt = json.loads(r.text.replace('nan', 'null'))
    ds = self._dbusservice
    ds['/History/ChargingCycles'] = int(lt['charge_starts'])
    ds['/History/ConnectorCycles'] = int(lt['connector_cycles'])
    ds['/History/Ac/Energy/Forward'] = int(lt['energy_wh'])
    ds['/History/Uptime'] = int(lt['uptime_s'])
    ds['/History/ChargingTime'] = int(lt['charging_time_s'])
    ds['/History/Alerts'] = int(lt['alert_count'])
    if lt['avg_startup_temp']:
        ds['/History/AverageStartupTemperature'] = int(lt['avg_startup_temp'])
    ds['/History/AbortedChargingCycles'] = int(lt['contactor_cycles_loaded'])
    ds['/History/ThermalFoldbacks'] = int(lt['thermal_foldbacks'])
    return lt

  def _update(self):
    r = requests.get(url = self.URL, timeout=10)
    d = r.json() 
    lt = self._lifetime()
    ds = self._dbusservice
    ds['/Ac/L1/Power'] = round(float(d['currentA_a']) * float(d['voltageA_v']))
    ds['/Ac/L2/Power'] = round(float(d['currentB_a']) * float(d['voltageB_v']))
    ds['/Ac/L3/Power'] = round(float(d['currentC_a']) * float(d['voltageC_v']))
    ds['/Ac/Power'] = round(ds['/Ac/L1/Power'] + ds['/Ac/L2/Power'] + ds['/Ac/L3/Power'])
    ds['/Ac/Frequency'] = round(d['grid_hz'], 1)
    ds['/Ac/Voltage'] = round(d['grid_v'])
    ds['/Current'] = round(d['vehicle_current_a'], 1)
    ds['/SetCurrent'] = 16  # static for now
    ds['/MaxCurrent'] = 16  # d['vehicle_current_a']
    # ds['/Ac/Energy/Forward'] = float(d['session_energy_wh']) / 1000.0
    ds['/Ac/Energy/Forward'] = round(float(lt['energy_wh']) / 1000.0, 3)
    ds['/ChargingTime'] = d['session_s']

    state = 0 # disconnected
    if d['vehicle_connected'] == True:
        state = 1 # connected
        if d['vehicle_current_a'] > 1:
            state = 2 # charging
    ds['/Status'] = state
    ds['/Mode'] = 0 # Manual, no control
    ds['/StartStop'] = 1 # Always on
    ds['/MCU/Temperature'] = d['mcu_temp_c']
    ds['/PCB/Temperature'] = d['pcba_temp_c']
    ds['/Handle/Temperature'] = d['handle_temp_c']

        # Update "fake" display through temperature monitors
    if True:
      self._tempservice['/CustomName'] = self._name + ' Handle'
      self._tempservice['/Temperature'] = round(d['handle_temp_c'], 1)
    else:
      if state == 2:
        twc_power = ds['/Ac/Power']
        self._tempservice['/CustomName'] = self._name + ' Charging [kW]'
        self._tempservice['/Temperature'] = round(twc_power/1000.0, 1)
      elif state == 1:
        self._tempservice['/CustomName'] = self._name + ' Car Connected [A]'
        self._tempservice['/Temperature'] = ds['/SetCurrent']
      else:
        self._tempservice['/CustomName'] = self._name + ' Idle [A]'
        self._tempservice['/Temperature'] = ds['/SetCurrent']

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

  parser = argparse.ArgumentParser()
  parser.add_argument('--ip', default='TeslaWallConnector.local', help='IP Address of Station')
  parser.add_argument('--service', default='com.victronenergy.evcharger.twc3', help='Service Name, e.g. for testing')
  parser.add_argument('--instance', default=42, help='Instance on DBUS, will be incremented by 100 in dryrun mode')
  parser.add_argument('--dryrun', dest='dryrun', action='store_true')
  parser.add_argument('--name', default='TWC3', help='User visible name of Wallbox')
  args = parser.parse_args()
  if args.ip:
      log.info('User supplied IP: %s' % args.ip)

  try:
    thread.daemon = True # allow the program to quit
  except NameError:
    pass

  from dbus.mainloop.glib import DBusGMainLoop
  # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
  DBusGMainLoop(set_as_default=True)

  for ip in args.ip.split(','):
    try:
      DbusTWC3Service(
        servicename=args.service + ('_dryrun' if args.dryrun else ''),
        deviceinstance=args.instance + (100 if args.dryrun else 0),
        ip=ip,
        name=args.name,
        dryrun=args.dryrun)
      log.info("Connected to TWC3 on ip %s" % ip)
      break
    except requests.exceptions.ConnectionError:
        log.info("Failed to connect to TWC3 on ip %s" % ip)
        time.sleep(1)

  log.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
  mainloop = gobject.MainLoop()
  mainloop.run()

if __name__ == "__main__":
  main()
