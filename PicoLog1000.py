#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import time
import ctypes
import logging

import numpy as np

if os.path.realpath('../TangoUtils') not in sys.path: sys.path.append(os.path.realpath('../TangoUtils'))

from config_logger import config_logger
from log_exception import log_exception
from picosdk.constants import PICO_STATUS
from picosdk.errors import ClosedDeviceError, ArgumentOutOfRangeError
from picosdk.pl1000 import pl1000
from picosdk.functions import assert_pico_ok

MAX_CAPTURE_SIZE = 1000000
US_LIMIT = 8096

class PicoLog1000:
    # config_logger
    # logger = logging.getLogger(__qualname__)
    # logger.propagate = False
    # # logger.setLevel(logging.DEBUG)
    # logger_f_str = '%(asctime)s,%(msecs)3d %(levelname)-7s %(filename)s %(funcName)s(%(lineno)s) %(message)s'
    # logger_log_formatter = logging.Formatter(logger_f_str, datefmt='%H:%M:%S')
    # logger_console_handler = logging.StreamHandler()
    # logger_console_handler.setFormatter(logger_log_formatter)
    # logger.addHandler(logger_console_handler)

    def __init__(self):
        self.logger = config_logger()
        self.logger.setLevel(logging.DEBUG)
        #
        self.handle = None
        self.opened = False
        self.last_status = None
        #
        self.range = 2.5  # [V] max value of input voltage
        self.max_adc = 4096  # [V] max ADC value corresponding to max input voltage
        self.scale = self.range / self.max_adc  # Volts per ADC quantum
        self.channels = []
        self.points = 1
        self.record_us = 10
        self.sampling = 0.010
        #
        self.trigger_enabled = 0
        self.trigger_channel = "PL1000_CHANNEL_1"
        self.trigger_edge = 0
        self.trigger_threshold = 2048
        self.trigger_hysteresis = 100
        self.trigger_delay = 10.0
        self.trigger_auto = False
        self.trigger_ms = 1000
        #
        self.data = None
        self.times = None
        self.timeout = None
        self.overflow = 0
        self.trigger = 0
        self.info = {}
        #
        self.recording_start_time = 0.0
        self.recording_end_time = 0.0
        self.record_in_progress = False
        self.read_time = 0.0
        #
        self.reconnect_enabled = False
        self.reconnect_timeout = 1.0
        self.reconnect_count = 3

    # def __del__(self):
    #     pass

    def open(self):
        try:
            self.handle = ctypes.c_int16()
            self.last_status = pl1000.pl1000OpenUnit(ctypes.byref(self.handle))
            assert_pico_ok(self.last_status)
            max_count = ctypes.c_uint16(0)
            self.last_status = pl1000.pl1000MaxValue(self.handle, ctypes.byref(max_count))
            assert_pico_ok(self.last_status)
            self.max_adc = max_count.value
            self.scale = self.range / self.max_adc
            self.opened = True
            self.logger.debug('PicoLog: Device has been opened')
        except:
            self.opened = False
            log_exception('Can not open picolog', exc_info=False)

    def assert_open(self):
        if self.handle is None or not self.opened:
            raise ClosedDeviceError("PicoLog is not opened")
        # !!!!
        # pl1000.pl1000SetInterval does not return correct status if Picolog is disconnected
        # self.ping() return -1.0 and correct status 'PICO_NOT_RESPONDING'
        # !!!!
        if self.ping() < 0.0:
            assert_pico_ok(self.last_status)
        # !!!!
        # handle = ctypes.c_int16()
        # progress = ctypes.c_int16()
        # complete = ctypes.c_int16()
        # stat = pl.pl1000OpenUnitProgress(ctypes.byref(handle), ctypes.byref(progress), ctypes.byref(complete))
        # assert_pico_ok(stat)
        # print('progress', handle, progress.value, complete.value)
        return True

    def get_info(self, request=None):
        try:
            self.assert_open()
        except:
            log_exception(exc_info=False)
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
            except KeyboardInterrupt:
                raise
            except:
                pass
        return {a: self.info[a] for a in sources}

    def set_do(self, do_number, do_value):
        self.assert_open()
        self.last_status = pl1000.pl1000SetDo(self.handle, ctypes.c_int16(do_value), ctypes.c_int16(do_number))
        assert_pico_ok(self.last_status)

    def get_single_value(self, channel):
        self.assert_open()
        result = ctypes.c_uint16(0)
        self.last_status = pl1000.pl1000GetSingle(self.handle, ctypes.c_int16(channel), ctypes.byref(result))
        assert_pico_ok(self.last_status)
        return result.value

    def get_max_value(self):
        self.assert_open()
        result = ctypes.c_uint16(0)
        self.last_status = pl1000.pl1000GetSingle(self.handle, ctypes.byref(result))
        assert_pico_ok(self.last_status)
        return result.value

    def set_pulse_width(self, period, cycle):
        self.assert_open()
        self.last_status = pl1000.pl1000SetPulseWidth(self.handle, ctypes.c_int16(period), ctypes.c_int8(cycle))
        assert_pico_ok(self.last_status)

    def check_pico_ok(self, status=None):
        if status is None:
            status = self.last_status
        return status == PICO_STATUS['PICO_OK']

    def check_limits(self, n_channels, points_per_channel, total_record_time):
        flag = True
        if not isinstance(n_channels, int):
            nc = len(n_channels)
        if nc <= 0 or nc > 16:
            self.logger.error('Channels can not be < 1 or > 16')
            return flag, n_channels, points_per_channel, total_record_time
        total_points = nc * points_per_channel
        if total_points > MAX_CAPTURE_SIZE:
            self.logger.error('Too many points requested - truncated fo %s' % MAX_CAPTURE_SIZE)
            points_per_channel = MAX_CAPTURE_SIZE // nc
            total_points = nc * channel_points
            flag = False
        interval = float(total_record_time) / total_points
        if (total_points <= US_LIMIT and interval < 1.0) or (total_points > US_LIMIT and interval < 10.0):
            flag = False
            self.logger.warning('Requested recording is too fast - corrected to minimum')
            if total_points <= US_LIMIT:
                interval = 1.0
            if total_points > US_LIMIT:
                interval = 10.0
            total_record_time = int(total_points * interval)
        return flag, n_channels, points_per_channel, total_record_time

    def set_timing(self, channels, channel_points, channel_record_us):
        nc = len(channels)
        if nc < 0:
            self.logger.error('Cannot be 0 or less channels')
            return False
        cp = channel_points
        total_points = nc * channel_points
        if total_points > MAX_CAPTURE_SIZE:
            self.logger.error('Too many points requested - truncated fo %s' % MAX_CAPTURE_SIZE)
            cp = MAX_CAPTURE_SIZE // nc
            total_points = nc * cp
            # return False
        interval = float(channel_record_us) / total_points
        cr = channel_record_us
        if (total_points <= US_LIMIT and interval < 1.0) or (total_points > US_LIMIT and interval < 10.0):
            self.logger.error('Requested recording is too fast - corrected')
            if total_points <= US_LIMIT:
                interval = 1
            if total_points > US_LIMIT:
                interval = 10
            cr = total_points * interval
        self.assert_open()
        cnls = (ctypes.c_int16 * nc)()
        for i in range(nc):
            cnls[i] = channels[i]
        t_us = ctypes.c_uint32(cr)
        n = ctypes.c_uint32(cp)
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
        self.logger.debug('PicoLog Timing: %s channels %s; sampling %s ms; %s points; duration %s us',
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
        self.overflow = 0
        self.recording_end_time = 0.0
        self.read_time = 0.0

    def ready(self):
        self.assert_open()
        ready = ctypes.c_int16(0)
        self.last_status = pl1000.pl1000Ready(self.handle, ctypes.byref(ready))
        assert_pico_ok(self.last_status)
        if ready.value:
            if self.recording_end_time == 0.0:
                self.recording_end_time = time.time()
        return ready.value

    def wait_result(self, timeout=None, use_timer=None):
        if use_timer is None:
            use_timer = True
            dt = 0.1
            t1 = time.time()
            time.sleep(dt)
            t2 = time.time()
            if (t2 - t1) < 0.9 * dt:
                self.logger.debug("Incorrect timer operation")
                use_timer = False
        if timeout is None:
            timeout = self.record_us * 1e-6 +0.05
        t0 = time.time()
        i = 0
        while not self.ready():
            if not use_timer:
                time.sleep(dt)
                i += 1
                if i*dt > timeout:
                    return False
            if (time.time() - t0) > timeout:
                return False
        return self.ready()

    def read(self, wait=0.0):
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
        self.trigger_enabled = enabled
        self.trigger_channel = channel
        self.trigger_edge = edge
        self.trigger_threshold = threshold
        self.trigger_hysteresis = hysteresis
        self.trigger_delay = delay_percent
        self.trigger_auto = auto_trigger
        self.trigger_ms = auto_ms

    def ping(self):
        t0 = time.time()
        self.last_status = pl1000.pl1000PingUnit(self.handle)
        if self.last_status == pl1000.PICO_STATUS['PICO_OK'] or \
                self.last_status == pl1000.PICO_STATUS['PICO_BUSY']:
            return time.time() - t0
        else:
            return -1.0

    def reconnect(self):
        if not self.reconnect_enabled:
            return
        if self.last_status != pl1000.PICO_STATUS['PICO_NOT_FOUND']:
            return
        self.reconnect_count -= 1
        if self.reconnect_count > 0:
            return
        if time.time() - self.reconnect_timeout >= 0.0:
            return
        try:
            status1 = pl1000.pl1000Stop(self.handle)
            status2 = pl1000.pl1000CloseUnit(self.handle)
            self.open()
            self.set_timing(self.channels, self.points, self.record_us)
            self.set_trigger(self.trigger_enabled, self.trigger_channel, self.trigger_edge,
                             self.trigger_threshold, self.trigger_hysteresis, self.trigger_delay,
                             self.trigger_auto, self.trigger_ms)
            self.reconnect_count = 3
            self.reconnect_timeout = time.time() + 5.0
        except KeyboardInterrupt:
            raise
        except:
            self.reconnect_timeout = time.time() + 5.0
            self.opened = False


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
    channel_points = 10000
    channel_record_us = 200000
    pl.set_timing([1, 2, 3, 4], channel_points, channel_record_us)
    pl.set_trigger(0, 1, 0, threshold=1024, delay_percent=-50.0)
    t0 = time.time()
    pl.start_recording()
    pl.wait_result()
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
