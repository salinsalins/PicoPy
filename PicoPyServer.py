#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PicoLog1216 tango device server"""

import sys
import os
import time
import logging
import numpy
import traceback
import math
from math import isnan
from threading import Thread, Lock
import winsound

import tango
from tango import AttrQuality, AttrWriteType, DispLevel, DevState, DebugIt
from tango.server import Device, attribute, command, pipe, device_property
# from Utils import *
import ctypes
from picosdk.pl1000 import pl1000 as pl
from picosdk.functions import adc2mVpl1000, assert_pico_ok

NaN = float('nan')


def config_logger(name: str = __name__, level: int = logging.DEBUG):
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.propagate = False
        logger.setLevel(level)
        f_str = '%(asctime)s,%(msecs)3d %(levelname)-7s %(filename)s %(funcName)s(%(lineno)s) %(message)s'
        log_formatter = logging.Formatter(f_str, datefmt='%H:%M:%S')
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)
    return logger


class PicoPyServer(Device):
    devices = []
    logger = config_logger(level=logging.DEBUG)
    beeped = True

    devicetype = attribute(label="type", dtype=str,
                           display_level=DispLevel.OPERATOR,
                           access=AttrWriteType.READ,
                           unit="", format="%s",
                           doc="PicoLog1216 tango device server")

    lastshottime = attribute(label="Last_shot_time", dtype=float,
                             display_level=DispLevel.OPERATOR,
                             access=AttrWriteType.READ,
                             unit=" s", format="%f",
                             doc="Time of the last shot")

    shotnumber = attribute(label="Shot_Number", dtype=int,
                           display_level=DispLevel.OPERATOR,
                           access=AttrWriteType.READ,
                           unit=" .", format="%d",
                           doc="Number of the last shot")

    ready = attribute(label="Ready", dtype=bool,
                      display_level=DispLevel.OPERATOR,
                      access=AttrWriteType.READ,
                      unit="", format="",
                      doc="Readiness of PicoLog1216")

    def init_device(self):
        # print(time_ms(), 'init_device entry', self)
        try:
            self.device_type_str = 'PicoLog1216 tango device server'
            self.last_shot_time = -1.0
            self.last_shot = -2
            self.device_name = self.get_name()
            self.device_proxy = tango.DeviceProxy(self.device_name)
            # read config from device properties
            level = self.get_device_property('log_level', 10)
            self.logger.setLevel(level)
            # input channels '1 2 4 12'
            self.channels = []
            cv = self.get_device_property('channels', '').split(' ')
            for v in cv:
                try:
                    self.channels.append(int(v))
                except:
                    pass
            # sampling interval and number of points
            self.samples = self.get_device_property('samples', 0)
            self.deltat = self.get_device_property('deltat', 0.001)
            # trigger
            self.trigger_enabled = self.get_device_property('trigger_enabled', 1)
            self.trigger_auto = self.get_device_property('trigger_auto', 0)
            self.trigger_auto_ms = self.get_device_property('trigger_auto_ms', 0)
            self.trigger_channel = self.get_device_property('trigger_channel', 1)
            self.trigger_dir = self.get_device_property('trigger_dir', 0)
            self.trigger_threshold = self.get_device_property('trigger_threshold', 100)
            self.trigger_hysteresis = self.get_device_property('trigger_hysteresis,', 10)
            self.trigger_delay = self.get_device_property('trigger_delay,', 0.0)
            # create handle
            self.set_state(DevState.INIT)
            self.handle = ctypes.c_int16()
            self.status = {}
            # open PicoLog 1000 device
            self.status["openUnit"] = pl.pl1000OpenUnit(ctypes.byref(self.handle))
            assert_pico_ok(self.status["openUnit"])
            # set sampling interval and number of points
            channels = ctypes.c_int16(len(self.channels))
            usForBlock = ctypes.c_uint32(self.samples * self.deltat * 1000000)
            noOfValues = ctypes.c_uint32(self.samples)

            self.status["setInterval"] = pl.pl1000SetInterval(self.handle, ctypes.byref(usForBlock), noOfValues,
                                                         ctypes.byref(channels), len(self.channels))
            assert_pico_ok(self.status["setInterval"])
            # set trigger
            self.status["setTrigger"] = pl.pl1000SetTrigger(self.handle, ctypes.c_uint16(self.trigger_enabled),
                                                            ctypes.c_uint16(self.trigger_auto),
                                                            ctypes.c_uint16(self.trigger_auto_ms),
                                                            ctypes.c_uint16(self.trigger_channel),
                                                            ctypes.c_uint16(self.trigger_dir),
                                                            ctypes.c_uint16(self.trigger_threshold),
                                                            ctypes.c_uint16(self.trigger_hysteresis),
                                                            ctypes.c_float(self.trigger_delay))
            assert_pico_ok(self.status["setTrigger"])

            msg = '%s PicoLog1216 started' % self.device_name
            self.logger.debug(msg)
            self.debug_stream(msg)
            self.set_state(DevState.RUNNING)
        except:
            msg = 'PicoLog1216 Exception creating device %s' % self.device_name
            self.logger.error(msg)
            self.error_stream(msg)
            self.logger.debug('', exc_info=True)
            self.set_state(DevState.FAULT)

    def delete_device(self):
        msg = '%s PicoLog1216 has been deleted' % self.device_name
        self.logger.info(msg)
        self.info_stream(msg)

    def read_devicetype(self):
        return self.device_type_str

    def read_lastshottime(self):
        if self.adc_device is None:
            PicoPyServer.logger.error('ADC is not present')
            self.error_stream('ADC is not present')
            return NaN
        elapsed = self.adc_device.read_attribute('Elapsed')
        t0 = time.time()
        if elapsed.quality != tango._tango.AttrQuality.ATTR_VALID:
            self.logger.warning('Non Valid attribute %s %s' % (elapsed.name, elapsed.quality))
        t = elapsed.time.tv_sec + (1.0e-6 * elapsed.time.tv_usec)
        # VasyaPy_Server.logger.debug('elapsed.value %s' % elapsed.value)
        # VasyaPy_Server.logger.debug('t0 %f' % t0)
        # VasyaPy_Server.logger.debug('elapsed read time %f' % t)
        self.last_shot_time = t0 - elapsed.value
        return self.last_shot_time

    def read_shotnumber(self):
        if self.adc_device is None:
            PicoPyServer.logger.error('ADC is not present')
            self.error_stream('ADC is not present')
            return -1
        self.last_shot = self.adc_device.read_attribute('Shot_id').value
        return self.last_shot

    def read_ready(self):
        if self.adc_device is not None and self.timer_device is not None:
            self.logger.error('ADC or timer is not present')
            self.error_stream('ADC or timer is not present')
            return False
        av = read_attribute_value(self.adc_device, 'chan16')
        av_coeff = read_coeff(self.adc_device, 'chan16')
        cc = self.adc_device.read_attribute('chan22')
        cc_coeff = read_coeff(self.adc_device, 'chan22')
        pr = self.timer_device.read_attribute('di60')
        if av.quality != tango._tango.AttrQuality.ATTR_VALID or \
                av.value * av_coeff < 8.0 or \
                cc.quality != tango._tango.AttrQuality.ATTR_VALID or \
                cc.value * cc_coeff < 0.1 or \
                not pr.value:
            return False
        else:
            return True

    @command(dtype_in=int)
    def setLogLevel(self, level):
        self.logger.setLevel(level)
        msg = '%s Log level set to %d' % (self.device_name, level)
        self.logger.info(msg)
        self.info_stream(msg)

    def get_device_property(self, prop: str, default=None):
        try:
            if not hasattr(self, 'device_proxy') or self.device_proxy is None:
                self.device_proxy = tango.DeviceProxy(self.device_name)
            pr = self.device_proxy.get_property(prop)[prop]
            result = None
            if len(pr) > 0:
                result = pr[0]
            if default is None:
                return result
            if result is None or result == '':
                result = default
            else:
                result = type(default)(result)
        except:
            result = default
        return result


def read_coeff(dev: None, attr: str):
    try:
        config = dev.get_attribute_config_ex(attr)[0]
        return float(config.display_unit)
    except:
        return 1.0


def read_attribute_value(dev: None, attr_name: str):
    try:
        attribute = dev.read_attribute(attr_name)
        coeff = read_coeff(dev, attr_name)
        return attribute.value * coeff
    except:
        return float('nan')


def post_init_callback():
    pass


def looping():
    time.sleep(0.3)
    # VasyaPy_Server.logger.debug('loop entry')
    for dev in PicoPyServer.devices:
        if dev.adc_device is not None and dev.timer_device is not None:
            mode = dev.timer_device.read_attribute('Start_mode').value
            # VasyaPy_Server.logger.debug('mode %s' % mode)
            if mode == 1:
                period = dev.timer_device.read_attribute('Period').value
                elapsed = dev.adc_device.read_attribute('Elapsed').value
                remained = period - elapsed
                if not PicoPyServer.beeped and remained < 1.0:
                    PicoPyServer.logger.debug('1 second to shot - Beep')
                    winsound.Beep(500, 300)
                    PicoPyServer.beeped = True
                if remained > 2.0:
                    PicoPyServer.beeped = False
    # VasyaPy_Server.logger.debug('loop exit')


if __name__ == "__main__":
    # VasyaPy_Server.run_server(post_init_callback=post_init_callback, event_loop=looping)
    PicoPyServer.run_server(event_loop=looping)
    # VasyaPy_Server.run_server()
