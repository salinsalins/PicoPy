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

from PicoLog1000 import *

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

    logger = config_logger(name=__qualname__, level=logging.DEBUG)

    device_type = attribute(label="type", dtype=str,
                            display_level=DispLevel.OPERATOR,
                            access=AttrWriteType.READ,
                            unit="", format="%s",
                            doc="Type of PicoLog1000 series device")

    info = attribute(label="info", dtype=str,
                     display_level=DispLevel.OPERATOR,
                     access=AttrWriteType.READ,
                     unit="", format="%s",
                     doc="Info of PicoLog1000 series device")

    # lastshottime = attribute(label="Last_shot_time", dtype=float,
    #                          display_level=DispLevel.OPERATOR,
    #                          access=AttrWriteType.READ,
    #                          unit=" s", format="%f",
    #                          doc="Time of the last shot")
    #
    # shotnumber = attribute(label="Shot_Number", dtype=int,
    #                        display_level=DispLevel.OPERATOR,
    #                        access=AttrWriteType.READ,
    #                        unit=" .", format="%d",
    #                        doc="Number of the last shot")
    #
    # ready = attribute(label="Ready", dtype=bool,
    #                   display_level=DispLevel.OPERATOR,
    #                   access=AttrWriteType.READ,
    #                   unit="", format="",
    #                   doc="Readiness of PicoLog")

    def init_device(self):
        if self not in PicoPyServer.devices:
            PicoPyServer.devices.append(self)
        self.device = None
        self.device_type = "Unknown PicoLog1000 series device"
        self.device_name = ''
        self.device_proxy = None
        self.channels = []
        self.init_result = None
        try:
            self.set_state(DevState.INIT)
            #
            self.device_name = self.get_name()
            self.device_proxy = tango.DeviceProxy(self.device_name)
            # read config from device properties
            level = self.get_device_property('log_level', 10)
            self.logger.setLevel(level)
            # config input channels "1, 2, 4, 12" -> [1, 2, 4, 12]
            cv = self.get_device_property('channels', '1').split(' ')
            for v in cv:
                try:
                    self.channels.append(int(v))
                except:
                    pass
            # sampling interval and number of points
            self.points = self.get_device_property('points_per_channel', 1000)
            self.record_us = self.get_device_property('channel_record_time_us', 1000000)
            # trigger
            self.trigger_enabled = self.get_device_property('trigger_enabled', 0)
            self.trigger_auto = self.get_device_property('trigger_auto', 0)
            self.trigger_auto_ms = self.get_device_property('trigger_auto_ms', 0)
            self.trigger_channel = self.get_device_property('trigger_channel', 1)
            self.trigger_dir = self.get_device_property('trigger_direction', 0)
            self.trigger_threshold = self.get_device_property('trigger_threshold', 2048)
            self.trigger_hysteresis = self.get_device_property('trigger_hysteresis,', 100)
            self.trigger_delay = self.get_device_property('trigger_delay,', 10.0)
            # create device
            self.device = PicoLog1000()
            self.device.logger = self.logger
            self.set_state(DevState.ON)
            # open PicoLog 1000 device
            self.device.open()
            self.set_state(DevState.OPEN)
            self.device.get_info()
            self.device_type = self.device.info['PICO_VARIANT_INFO']
            # set sampling interval and number of points
            self.device.set_timing(self.channels, self.points, self.record_us)
            # set trigger
            self.device.set_trigger(self.trigger_enabled, self.trigger_auto,
                                    self.trigger_auto_ms, self.trigger_channel, self.trigger_dir,
                                    self.trigger_threshold, self.trigger_hysteresis, self.trigger_delay)
            msg = '%s %s has been initialized' % (self.device_name, self.device_type)
            self.logger.info(msg)
            self.info_stream(msg)
            self.set_state(DevState.STANDBY)
        except Exception as ex:
            self.init_result = ex
            msg = 'Exception initialization PicoLog device %s' % self.device_name
            self.logger.error(msg)
            self.error_stream(msg)
            self.logger.debug('', exc_info=True)
            self.set_state(DevState.FAULT)

    def delete_device(self):
        try:
            self.device.stop()
        except:
            pass
        try:
            self.device.close()
        except:
            pass
        self.set_state(DevState.OFF)
        msg = '%s PicoLog has been deleted' % self.device_name
        self.logger.info(msg)
        self.info_stream(msg)

    def read_device_type(self):
        return self.device_type_str

    def read_info(self):
        return str(self.device.info)

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
        return self.device.ready()

    @command(dtype_in=int)
    def setLogLevel(self, level):
        self.logger.setLevel(level)
        msg = '%s Log level set to %d' % (self.device_name, level)
        self.logger.info(msg)
        self.info_stream(msg)

    @command(dtype_in=int)
    def startRecording(self, wait):
        self.device.run()
        msg = '%s Recording started' % self.device_name
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
    # PicoPyServer.run_server(post_init_callback=post_init_callback, event_loop=looping)
    PicoPyServer.run_server(event_loop=looping)
