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
                     display_level=DispLevel.EXPERT,
                     access=AttrWriteType.READ,
                     unit="", format="%s",
                     doc="Info of PicoLog1000 series device")

    ping = attribute(label="ping_time", dtype=float,
                     display_level=DispLevel.OPERATOR,
                     access=AttrWriteType.READ,
                     unit=" s", format="%f",
                     doc="Ping time")

    scale = attribute(label="scale", dtype=float,
                      display_level=DispLevel.OPERATOR,
                      access=AttrWriteType.READ,
                      unit="V", format="%f",
                      doc="Volts per quantum")

    trigger = attribute(label="trigger", dtype=float,
                        display_level=DispLevel.OPERATOR,
                        access=AttrWriteType.READ,
                        unit="", format="%10.0f",
                        doc="Trigger index")

    overflow = attribute(label="overflow", dtype=int,
                         display_level=DispLevel.OPERATOR,
                         access=AttrWriteType.READ,
                         unit="", format="%d",
                         doc="Was the overflow in recorded data")

    sampling = attribute(label="sampling", dtype=float,
                         display_level=DispLevel.OPERATOR,
                         access=AttrWriteType.READ,
                         unit="ms", format="%f",
                         doc="Sampling in milliseconds between points in each channel")

    raw_data = attribute(label="raw_data", dtype=[[numpy.uint16]],
                         max_dim_y=16,
                         max_dim_x=1000000,
                         display_level=DispLevel.OPERATOR,
                         access=AttrWriteType.READ,
                         unit="V", format="%f",
                         doc="Raw data in ADC quanta")

    # times = attribute(label="times", dtype=[[numpy.float64]],
    #                   max_dim_x=16,
    #                   max_dim_y=1000000,
    #                   display_level=DispLevel.OPERATOR,
    #                   access=AttrWriteType.READ,
    #                   unit="s", format="%f",
    #                   doc="ADC acquisition time in seconds")
    #

    chany1 = attribute(label="Raw_Data_Channel_1", dtype=[numpy.uint16],
                       min_value=0,
                       max_value=4095,
                       max_dim_x=1000000,
                       max_dim_y=0,
                       display_level=DispLevel.OPERATOR,
                       access=AttrWriteType.READ,
                       unit="V", format="%5.3f",
                       doc="Data for channel 1 in ADC quanta")

    chanx1 = attribute(label="Time_Channel_1", dtype=[numpy.float32],
                       #min_value=0,
                       #max_value=4095,
                       max_dim_x=1000000,
                       max_dim_y=0,
                       display_level=DispLevel.OPERATOR,
                       access=AttrWriteType.READ,
                       unit="ms", format="%5.3f",
                       doc="Times for channel 1 in ms")

    record_in_progress = attribute(label="record_in_progress", dtype=bool,
                                   display_level=DispLevel.OPERATOR,
                                   access=AttrWriteType.READ,
                                   unit="", format="",
                                   doc="Is record operation in progress")

    data_ready = attribute(label="data_ready", dtype=bool,
                           display_level=DispLevel.OPERATOR,
                           access=AttrWriteType.READ,
                           unit="", format="",
                           doc="Is data ready for reading")

    def init_device(self):
        if self not in PicoPyServer.devices:
            PicoPyServer.devices.append(self)
        self.device = None
        self.device_type_str = "Unknown PicoLog1000 series device"
        self.device_name = ''
        self.device_proxy = None
        self.channels = []
        self.record_initiated = False
        self.data_ready_value = False
        self.init_result = None
        try:
            self.set_state(DevState.INIT)
            #
            self.device_name = self.get_name()
            self.device_proxy = tango.DeviceProxy(self.device_name)
            # read config from device properties
            level = self.get_device_property('log_level', 10)
            self.logger.setLevel(level)
            # create PicoLog1000 device
            self.device = PicoLog1000()
            self.set_state(DevState.ON)
            # change logger to class
            self.device.logger = self.logger
            # open PicoLog1000 device
            self.device.open()
            self.set_state(DevState.OPEN)
            self.device.get_info()
            self.device_type_str = self.device.info['PICO_VARIANT_INFO']
            # set sampling interval channels and number of points
            self.set_sampling()
            # set trigger
            self.set_trigger()
            # OK message
            msg = '%s %s has been initialized' % (self.device_name, self.device_type_str)
            self.logger.info(msg)
            self.info_stream(msg)
            self.set_state(DevState.STANDBY)
            self.init_result = None
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

    def read_ping(self):
        # self.logger.debug('enter')
        try:
            v = self.device.ping()
            # self.logger.debug(self.device.get_last_status())
            return v
        except:
            self.logger.debug('', exc_info=True)
            return -1.0

    def read_scale(self):
        try:
            return self.device.scale
        except:
            return 0.0

    def read_trigger(self):
        try:
            return self.device.trigger
        except:
            return 0.0

    def read_overflow(self):
        try:
            return self.device.overflow
        except:
            return 0.0

    def read_sampling(self):
        try:
            return self.device.sampling
        except:
            return 0.0

    def read_chany1(self):
        if self.data_ready_value:
            self.logger.debug('reading chany1, size %s', self.device.data[0, :].shape)
            return self.device.data[0, :]
        else:
            msg = '%s data is not ready' % self.device_name
            self.logger.warning(msg)
            self.error_stream(msg)
            # self.logger.debug('', exc_info=True)
            return []

    def read_raw_data(self):
        if self.data_ready_value:
            self.logger.debug('reading data size %s', self.device.data.shape)
            return self.device.data
        else:
            msg = '%s data is not ready' % self.device_name
            self.logger.error(msg)
            self.error_stream(msg)
            # self.logger.debug('', exc_info=True)
            return []

    def read_chanx1(self):
        if self.data_ready_value:
            return self.device.times[0, :]
        else:
            msg = '%s data is not ready' % self.device_name
            self.logger.error(msg)
            self.error_stream(msg)
            # self.logger.debug('', exc_info=True)
            return []

    def read_record_in_progress(self):
        return self.record_initiated

    def read_data_ready(self):
        return self.data_ready_value

    def set_sampling(self):
        # config input channels "1, 2, 4, 12" -> [1, 2, 4, 12]
        cv = self.get_device_property('channels', '1').split(' ')
        self.channels = []
        for v in cv:
            try:
                self.channels.append(int(v))
            except:
                pass
        # read sampling interval and number of points
        self.points = self.get_device_property('points_per_channel', 1000)
        self.record_us = self.get_device_property('channel_record_time_us', 1000000)
        # set sampling interval and number of points
        self.device.set_timing(self.channels, self.points, self.record_us)
        # set properties for chany1
        self.set_channel_properties(self.chany1, self.device.data[0, :])
        self.set_channel_properties(self.raw_data, self.device.data)
        self.chanx1.set_value(self.device.times[0, :])

    def set_channel_properties(self, chan, value=None, props=None):
        if props is None:
            props = {}
        prop = chan.get_properties()
        prop.display_unit = self.device.scale
        prop.max_value = self.device.max_adc
        try:
            for p in props:
                if hasattr(chan, p):
                    setattr(chan, p, props[p])
        except:
            pass
        chan.set_properties(prop)
        if value is not None:
            chan.set_value(value)

    def set_trigger(self):
        # set trigger
        self.trigger_enabled = self.get_device_property('trigger_enabled', 0)
        self.trigger_auto = self.get_device_property('trigger_auto', 0)
        self.trigger_auto_ms = self.get_device_property('trigger_auto_ms', 0)
        self.trigger_channel = self.get_device_property('trigger_channel', 1)
        self.trigger_dir = self.get_device_property('trigger_direction', 0)
        self.trigger_threshold = self.get_device_property('trigger_threshold', 2048)
        self.trigger_hysteresis = self.get_device_property('trigger_hysteresis,', 100)
        self.trigger_delay = self.get_device_property('trigger_delay,', 10.0)
        self.device.set_trigger(self.trigger_enabled, self.trigger_channel,
                                self.trigger_dir, self.trigger_threshold,
                                self.trigger_hysteresis, self.trigger_delay,
                                self.trigger_auto, self.trigger_auto_ms)

    @command(dtype_in=int)
    def set_log_level(self, level):
        self.logger.setLevel(level)
        msg = '%s Log level set to %d' % (self.device_name, level)
        self.logger.info(msg)
        self.info_stream(msg)

    @command(dtype_in=int)
    def start_recording(self, value):
        try:
            if value:
                if not self.device.ready() or self.record_initiated:
                    msg = '%s Can not start - record in progress' % self.device_name
                    self.logger.info(msg)
                    self.info_stream(msg)
                    return
            self.record_initiated = True
            self.data_ready_value = False
            self.device.run()
            msg = '%s Recording started' % self.device_name
            self.logger.info(msg)
            self.info_stream(msg)
        except:
            self.record_initiated = False
            self.data_ready_value = False
            self.logger.debug('', exc_info=True)

    @command(dtype_in=None)
    def read_config(self):
        self.set_sampling()
        # set trigger
        self.set_trigger()
        msg = '%s Config applied' % self.device_name
        self.logger.debug(msg)
        self.debug_stream(msg)

    @command(dtype_in=None)
    def stop_recording(self):
        try:
            self.device.stop()
            self.record_initiated = False
            self.data_ready_value = False
            msg = '%s Recording stopped' % self.device_name
            self.logger.info(msg)
            self.info_stream(msg)
        except:
            self.record_initiated = False
            self.data_ready_value = False
            self.logger.debug('', exc_info=True)

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


def looping():
    time.sleep(0.01)
    for dev in PicoPyServer.devices:
        #print(dev.device.times[0, :20])
        #dev.read_attribute('chanx1').value[:20]
        if dev.record_initiated:
            try:
                if dev.device.ready():
                    msg = '%s recording finished, reading data' % dev.device_name
                    dev.logger.info(msg)
                    dev.info_stream(msg)
                    dev.device.read()
                    dev.record_initiated = False
                    dev.data_ready_value = True
                    msg = '%s reading finished, data is ready' % dev.device_name
                    dev.logger.info(msg)
                    dev.info_stream(msg)
            except:
                dev.record_initiated = False
                dev.data_ready_value = False
                msg = '%s reading data error' % dev.device_name
                dev.logger.info(msg)
                dev.info_stream(msg)
                dev.logger.debug('', exc_info=True)
    # PicoPyServer.logger.debug('loop exit')


if __name__ == "__main__":
    # PicoPyServer.run_server(post_init_callback=post_init_callback, event_loop=looping)
    PicoPyServer.run_server(event_loop=looping)
