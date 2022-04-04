#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import ctypes
import logging

import numpy as np

from picosdk.constants import PICO_STATUS
from picosdk.errors import ClosedDeviceError, ArgumentOutOfRangeError
from picosdk.pl1000 import pl1000
from picosdk.functions import assert_pico_ok


class PicoLog1000:
    # config_logger
    logger = logging.getLogger(__qualname__)
    logger.propagate = False
    # logger.setLevel(logging.DEBUG)
    logger_f_str = '%(asctime)s,%(msecs)3d %(levelname)-7s %(filename)s %(funcName)s(%(lineno)s) %(message)s'
    logger_log_formatter = logging.Formatter(logger_f_str, datefmt='%H:%M:%S')
    logger_console_handler = logging.StreamHandler()
    logger_console_handler.setFormatter(logger_log_formatter)
    logger.addHandler(logger_console_handler)

    def __init__(self):
        self.handle = None
        self.opened = False
        self.last_status = None
        #
        self.range = 2.5  # [V] max value of input voltage
        self.max_adc = 4096  # [V] max ADC value corresponding to max input voltage
        self.scale = self.range / self.max_adc  # self.range/self.max_adc Volts per ADC quantum
        self.channels = []
        self.points = 0
        self.record_us = 0
        self.sampling = 0.0
        self.data = None
        self.times = None
        self.timeout = None
        self.overflow = 0
        self.trigger = 0
        self.info = {}
        #
        self.recording_start_time = 0.0
        self.read_time = 0.0
        self.t0 = time.time()
        #
        self.logger.setLevel(logging.DEBUG)

    # def __del__(self):
    #     pass

    def open(self):
        self.t0 = time.time()
        self.handle = ctypes.c_int16()
        self.last_status = pl1000.pl1000OpenUnit(ctypes.byref(self.handle))
        assert_pico_ok(self.last_status)
        max_count = ctypes.c_uint16()
        self.last_status = pl1000.pl1000MaxValue(self.handle, ctypes.byref(max_count))
        assert_pico_ok(self.last_status)
        self.max_adc = max_count.value
        self.scale = self.range / self.max_adc
        self.opened = True
        self.logger.debug('PicoLog: Device has been opened')

    def assert_open(self, value=True):
        self.t0 = time.time()
        if not self.opened:
            raise ClosedDeviceError("PicoLog is not opened")
        if not value:
            raise ArgumentOutOfRangeError("Value out of range")
        # handle = ctypes.c_int16()
        # progress = ctypes.c_int16()
        # complete = ctypes.c_int16()
        # stat = pl.pl1000OpenUnitProgress(ctypes.byref(handle), ctypes.byref(progress), ctypes.byref(complete))
        # assert_pico_ok(stat)
        # print('progress', handle, progress.value, complete.value)

    def get_info(self, request=None):
        self.assert_open()
        if isinstance(request, str):
            sources = {request: pl1000.PICO_INFO[request]}
        elif request is None:
            sources = pl1000.PICO_INFO
        else:
            sources = {a: pl1000.PICO_INFO[a] for a in request}
        length = ctypes.c_int16(10)
        for i in sources:
            self.info[i] = ''
            v = pl1000.PICO_INFO[i]
            try:
                self.last_status = pl1000.pl1000GetUnitInfo(self.handle, None, length,
                                                            ctypes.byref(length), v)
                out_info = (ctypes.c_int8 * length.value)()
                self.last_status = pl1000.pl1000GetUnitInfo(self.handle, out_info, length.value,
                                                            ctypes.byref(length), v)
                assert_pico_ok(self.last_status)
                for j in range(len(out_info) - 1):
                    self.info[i] += chr(out_info[j])
            except:
                pass
        return {a: self.info[a] for a in sources}

    def set_do(self, do_number, do_value):
        self.assert_open()
        self.last_status = pl1000.pl1000SetDo(self.handle, ctypes.c_int16(do_value), ctypes.c_int16(do_number))
        assert_pico_ok(self.last_status)

    def set_pulse_width(self, period, cycle):
        self.assert_open()
        self.last_status = pl1000.pl1000SetPulseWidth(self.handle, ctypes.c_int16(period), ctypes.c_int8(cycle))
        assert_pico_ok(self.last_status)


    def set_timing(self, channels, channel_points, channel_record_us):
        self.assert_open()
        nc = len(channels)
        cnls = (ctypes.c_int16 * nc)()
        for i in range(nc):
            cnls[i] = channels[i]
        t_us = ctypes.c_uint32(channel_record_us)
        n = ctypes.c_uint32(channel_points)
        self.last_status = pl1000.pl1000SetInterval(self.handle, ctypes.byref(t_us),
                                                    n, ctypes.byref(cnls), nc)
        assert_pico_ok(self.last_status)
        self.channels = channels
        self.points = n.value
        self.record_us = t_us.value
        if self.points != channel_points:
            self.logger.warning('PicoLog: number of points corrected from %s to %s us',
                                channel_points, self.points)
        if self.record_us != channel_record_us:
            self.logger.warning('PicoLog: channel record time has been corrected from %s to %s us',
                                channel_record_us, self.record_us)
        self.sampling = (0.001 * self.record_us) / self.points
        self.logger.debug('PicoLog: Timing: %s channels %s; sampling %s ms; %s points; duration %s us',
                          len(self.channels), self.channels, self.sampling, self.points, self.record_us)
        # create array for data
        self.data = np.empty((len(self.channels), self.points), dtype=np.uint16, order='F')
        # and timings
        # fill timings array
        self.t = np.linspace(0.0, (self.points - 1) * self.sampling, self.points, dtype=np.float32)
        self.times = np.empty(self.data.shape, dtype=np.float32)
        for i in range(len(self.channels)):
            self.times[i, :] = self.t + (i * self.sampling / len(self.channels))
        if self.points != channel_points or self.record_us != channel_record_us:
            return False
        return True

    def get_last_status(self, stat=None):
        if stat is None:
            stat = self.last_status
        return PICO_STATUS.get(stat, "UNKNOWN")

    def start_recording(self, n_values=None, mode="BM_SINGLE"):
        # start data recording
        self.assert_open()
        if isinstance(mode, str):
            m = pl1000.PL1000_BLOCK_METHOD[mode]
        else:
            m = mode
        if n_values is None:
            n = ctypes.c_uint32(self.points)
        elif not isinstance(n_values, ctypes.c_uint32):
            n = ctypes.c_uint32(n_values)
        else:
            n = n_values
        self.last_status = pl1000.pl1000Run(self.handle, n, m)
        assert_pico_ok(self.last_status)
        self.recording_start_time = time.time()

    def ready(self):
        self.assert_open()
        ready = ctypes.c_int16(0)
        self.last_status = pl1000.pl1000Ready(self.handle, ctypes.byref(ready))
        assert_pico_ok(self.last_status)
        return ready.value

    def wait_result(self, timeout=None):
        if timeout is None:
            timeout = self.timeout
        if timeout is None:
            return self.ready()
        t0 = time.time()
        while not self.ready():
            if (time.time() - t0) > timeout:
                return False
        return self.ready()

    def read(self, wait=0.0):
        self.assert_open()
        if wait > 0.0:
            self.wait_result(wait)
        if not self.ready():
            self.logger.warning('PicoLog: read - device is not ready')
        overflow = ctypes.c_uint16()
        trigger = ctypes.c_uint32()
        n = ctypes.c_uint32(self.points)
        self.last_status = pl1000.pl1000GetValues(self.handle, self.data.ctypes, ctypes.byref(n),
                                                  ctypes.byref(overflow), ctypes.byref(trigger))
        assert_pico_ok(self.last_status)
        self.read_time = time.time()
        self.overflow = overflow.value
        self.trigger = trigger.value
        if self.points != n.value:
            self.logger.warning('PicoLog: data partial reading %s of %s', n.value, self.points)

    def close(self):
        self.last_status = pl1000.pl1000CloseUnit(self.handle)
        assert_pico_ok(self.last_status)

    def stop(self):
        self.assert_open()
        self.last_status = pl1000.pl1000Stop(self.handle)
        assert_pico_ok(self.last_status)

    def set_trigger(self, enabled=0, channel="PL1000_CHANNEL_1", edge=0,
                    threshold=2048, hysteresis=100, delay_percent=10.0,
                    auto_trigger=False, auto_ms=1000):
        self.assert_open()
        if isinstance(channel, str):
            channel = pl1000.PL1000Inputs[channel]
        self.last_status = pl1000.pl1000SetTrigger(self.handle, ctypes.c_uint16(int(enabled)),
                                                   ctypes.c_uint16(int(auto_trigger)), ctypes.c_uint16(int(auto_ms)),
                                                   ctypes.c_uint16(int(channel)), ctypes.c_uint16(int(edge)),
                                                   ctypes.c_uint16(int(threshold)), ctypes.c_uint16(int(hysteresis)),
                                                   delay_percent)
        assert_pico_ok(self.last_status)

    def ping(self):
        t0 = time.time()
        self.last_status = pl1000.pl1000PingUnit(self.handle)
        if self.last_status == pl1000.PICO_STATUS['PICO_OK'] or \
                self.last_status == pl1000.PICO_STATUS['PICO_BUSY']:
            return time.time() - t0
        else:
            return -1.0

#
# class FakePicoLog1000(PicoLog1000):
#
#     def ready(self, wait=False, timeout=None):
#         self.assert_open()
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#         return True
#
#     def read(self, wait=False):
#         self.assert_open()
#         if wait:
#             self.ready(True)
#         if not self.ready():
#             self.logger.warning('Read on not ready device')
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#         self.read_time = time.time()
#         self.overflow = 0
#         self.trigger = 100
#
#     def close(self):
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#
#     def stop(self):
#         self.assert_open()
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#
#     def set_trigger(self, enabled=False, channel="PL1000_CHANNEL_1", edge=0,
#                     threshold=2048, hysteresis=100, delay_percent=10.0,
#                     auto_trigger=False, auto_ms=1000):
#         self.assert_open()
#         if isinstance(channel, str):
#             channel = pl1000.PL1000Inputs[channel]
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#
#     def ping(self):
#         t0 = time.time()
#         self.last_status = pl1000.PICO_STATUS['PICO_OK']
#         return time.time() - t0
#

if __name__ == "__main__":
    pl = PicoLog1000()
    pl.open()
    pl.set_timing([1, 2, 3, 4], 10000, 200000)
    pl.set_trigger(0, 1, 0, 1024, -50.0)
    t0 = time.time()
    pl.start_recording()
    pl.wait_result(5.0)
    pl.read()
    pl.close()
    print('Reading completed in', time.time() - t0, 'seconds')

    import matplotlib.pyplot as plt

    for i in range(len(pl.channels)):
        plt.plot(pl.times[i, :], pl.data[i, :] * pl.scale * 1000)
    plt.xlabel('Time (ms)')
    plt.ylabel('Voltage (mV)')
    plt.legend([str(i) for i in pl.channels])
    plt.show()
