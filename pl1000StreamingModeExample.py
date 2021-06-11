#
# Copyright (C) 2019 Pico Technology Ltd. See LICENSE file for terms.
#
# PL1000 SINGLE MODE EXAMPLE
# This example opens a pl1000 device, sets up the device for capturing data from channel 1.
# Then this example collect a sample from channel 1 and displays it on the console.

import ctypes
import numpy as np

from picosdk.errors import ClosedDeviceError, ArgumentOutOfRangeError
from picosdk.pl1000 import pl1000 as pl
import matplotlib.pyplot as plt
from picosdk.functions import adc2mVpl1000, assert_pico_ok
import time


class PicoLog1000:
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
        self.delta_t = 0
        self.sampling = 0
        self.data = None
        self.times = None
        self.info = None
        self.timeout = None
        self.overflow = None
        self.trigger = None
        #
        self.t0 = time.time()

    # def __del__(self):
    #     pass

    def open(self):
        self.t0 = time.time()
        self.handle = ctypes.c_int16()
        self.last_status = pl.pl1000OpenUnit(ctypes.byref(self.handle))
        assert_pico_ok(self.last_status)
        max_count = ctypes.c_uint16()
        self.last_status = pl.pl1000MaxValue(self.handle, ctypes.byref(max_count))
        assert_pico_ok(self.last_status)
        self.max_adc = max_count.value
        self.scale = self.range / self.max_adc
        self.opened = True

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

    def get_info(self, info=pl.PICO_INFO["PICO_HARDWARE_VERSION"]):
        self.assert_open()
        length = ctypes.c_int16(10)
        self.last_status = pl.pl1000GetUnitInfo(self.handle, None, length,
                                                ctypes.byref(length), info)
        self.info = (ctypes.c_int8 * length.value)()
        self.last_status = pl.pl1000GetUnitInfo(self.handle, self.info, length.value,
                                                ctypes.byref(length), info)
        assert_pico_ok(self.last_status)
        return self.info

    def set_do(self, do_number, do_value):
        self.assert_open()
        self.last_status = pl.pl1000SetDo(self.handle, ctypes.c_int16(do_value), ctypes.c_int16(do_number))
        assert_pico_ok(self.last_status)

    def set_pulse_width(self, period, cycle):
        self.assert_open()
        self.last_status = pl.pl1000SetPulseWidth(self.handle, ctypes.c_int16(period), ctypes.c_int8(cycle))
        assert_pico_ok(self.last_status)

    def set_interval(self, channels, channel_n_points, channel_record_t_us):
        self.assert_open()
        nc = len(channels)
        cnls = (ctypes.c_int16 * nc)()
        for i in range(nc):
            cnls[i] = channels[i]
        t_us = ctypes.c_uint32(channel_record_t_us)
        n = ctypes.c_uint32(channel_n_points)
        self.last_status = pl.pl1000SetInterval(self.handle, ctypes.byref(t_us),
                                                n, ctypes.byref(cnls), nc)
        assert_pico_ok(self.last_status)
        self.channels = channels
        self.points = n.value
        self.delta_t = t_us.value
        self.sampling = (0.001 * self.delta_t) / self.points
        # create array for data
        self.data = np.empty((nc, self.points), dtype=np.uint16, order='F')
        t = np.linspace(0, (self.points - 1) * self.sampling, self.points)
        self.times = np.empty_like(self.data)
        for i in range(nc):
            self.times[i, :] = t + (i * self.sampling / len(self.channels))
        if self.delta_t != channel_record_t_us or self.points != channel_n_points:
            print('Sampling interval has been corrected to', self.sampling, 'ms')
            return False
        return True

    def run(self, n_values=None, mode=pl.PL1000_BLOCK_METHOD["BM_SINGLE"], wait=False):
        # start streaming
        self.assert_open()
        if n_values is None:
            n = ctypes.c_uint32(self.points)
        if not isinstance(n_values, ctypes.c_uint32):
            n = ctypes.c_uint32(n_values)
        else:
            n = n_values
        self.last_status = pl.pl1000Run(self.handle, n, mode)
        assert_pico_ok(self.last_status)
        if wait:
            self.ready(True)

    def ready(self, wait=False, timeout=None):
        self.assert_open()
        t0 = time.time()
        ready = ctypes.c_int16(0)
        self.last_status = pl.pl1000Ready(self.handle, ctypes.byref(ready))
        if wait:
            if self.timeout is not None and timeout is None:
                timeout = self.timeout
            while not ready.value:
                # print('*')
                if timeout is not None and time.time() - t0 > timeout:
                    break
                self.last_status = pl.pl1000Ready(self.handle, ctypes.byref(ready))
            assert_pico_ok(self.last_status)
        assert_pico_ok(self.last_status)
        return ready.value

    def read(self, wait=False):
        self.assert_open()
        if wait:
            self.ready(True)
        overflow = ctypes.c_uint16()
        trigger = ctypes.c_uint32()
        n = ctypes.c_uint32(self.points)
        self.last_status = pl.pl1000GetValues(self.handle, self.data.ctypes, ctypes.byref(n),
                                              ctypes.byref(overflow), ctypes.byref(trigger))
        assert_pico_ok(self.last_status)
        self.overflow = overflow.value
        self.trigger = trigger.value
        if self.points != n.value:
            print('Data partial reading', n.value, 'of', self.points)
        # convert ADC counts to V
        y = self.data * self.scale
        return self.times, y

    def close(self):
        self.last_status = pl.pl1000CloseUnit(self.handle)
        assert_pico_ok(self.last_status)

    def stop(self):
        self.assert_open()
        self.last_status = pl.pl1000Stop(self.handle)
        assert_pico_ok(self.last_status)

    def set_trigger(self, enabled=False, channel=pl.PL1000Inputs["PL1000_CHANNEL_1"], edge=0,
                    threshold=2048, hysteresis=100, delay_percent=10.0, auto_trigger=False, auto_ms=1000):
        self.assert_open()
        self.last_status = pl.pl1000SetTrigger(self.handle, ctypes.c_uint16(enabled),
                                               ctypes.c_uint16(auto_trigger), ctypes.c_uint16(auto_ms),
                                               ctypes.c_uint16(channel), ctypes.c_uint16(edge),
                                               ctypes.c_uint16(threshold), ctypes.c_uint16(hysteresis),
                                               delay_percent)
        assert_pico_ok(self.last_status)

    def ping(self):
        self.last_status = pl.pl1000Ping(self.handle)
        return self.last_status

# Create chandle and status ready for use
chandle = ctypes.c_int16()
status = {}

# open PicoLog 1000 device
txt = "openUnit"
print('---', txt)
t0 = time.time()
status[txt] = pl.pl1000OpenUnit(ctypes.byref(chandle))
print('elapsed time', time.time() - t0, 's')
print(txt, 'status', status[txt])
assert_pico_ok(status[txt])

stat = pl.pl1000SetDo(chandle, ctypes.c_int16(1), ctypes.c_int16(1))
assert_pico_ok(stat)

stat = pl.pl1000SetPulseWidth(chandle, ctypes.c_int16(1000), ctypes.c_int8(50))
assert_pico_ok(stat)

# length = ctypes.c_int16(10)
# info = (ctypes.c_int8 * length.value)()
# stat = pl.pl1000GetUnitInfo(chandle, None, length, ctypes.byref(length), pl.PICO_INFO['PICO_DRIVER_VERSION'])
# assert_pico_ok(stat)
# info = (ctypes.c_int8 * length.value)()
# stat = pl.pl1000GetUnitInfo(chandle, ctypes.byref(info), length, ctypes.byref(length), pl.PICO_INFO['PICO_DRIVER_VERSION'])
# assert_pico_ok(stat)

dt_us = 1000000
n = 1000
cnls = (1, 2, 4, 7, 12, 15)
nc = len(cnls)
# set sampling interval
usForBlock = ctypes.c_uint32(dt_us)
noOfValues = ctypes.c_uint32(n)
channels = (ctypes.c_int16 * nc)()
for i in range(len(cnls)):
    channels[i] = cnls[i]

txt = "setInterval"
print('---', txt)
t0 = time.time()
status[txt] = pl.pl1000SetInterval(chandle, ctypes.byref(usForBlock), noOfValues, ctypes.byref(channels), nc)
print('elapsed time', time.time() - t0, 's')
print(txt, 'status', status[txt])
assert_pico_ok(status[txt])
print('noOfValues', noOfValues.value, n)
print('usForBlock', usForBlock.value, dt_us)

ready = ctypes.c_int16(0)
# ready.value = False

# start streaming
# mode = pl.PL1000_BLOCK_METHOD["BM_STREAM"]
mode = pl.PL1000_BLOCK_METHOD["BM_SINGLE"]
txt = "run"
print('---', txt)
t0 = time.time()
status[txt] = pl.pl1000Run(chandle, noOfValues, mode)
print(txt, 'status', status[txt])
assert_pico_ok(status[txt])
print('elapsed time', time.time() - t0, 's')
print('noOfValues', noOfValues.value)
print('usForBlock', usForBlock.value)

print('')
print('--- wait ---')

# sleep(usForBlock.value / 1000000 + 0.5)

while not ready.value:
    # print('*')
    st = pl.pl1000Ready(chandle, ctypes.byref(ready))
    assert_pico_ok(st)
print('elapsed time', time.time() - t0, 's')
print('noOfValues', noOfValues.value)
print('usForBlock', usForBlock.value)

values = (ctypes.c_uint16 * (noOfValues.value * nc))()
oveflow = ctypes.c_uint16()
trigger = ctypes.c_uint32()
# print('len(values)', len(values), noOfValues.value)

txt = "getValues"
print('---', txt)
t0 = time.time()
status[txt] = pl.pl1000GetValues(chandle, ctypes.byref(values), ctypes.byref(noOfValues), ctypes.byref(oveflow),
                                 ctypes.byref(trigger))
y = np.zeros((nc, noOfValues.value), dtype=np.uint16, order='F')
st = pl.pl1000GetValues(chandle, y.ctypes, ctypes.byref(noOfValues), ctypes.byref(oveflow), ctypes.byref(trigger))
assert_pico_ok(st)
print('status', txt, status[txt])
print('elapsed time', time.time() - t0, 's')
assert_pico_ok(status[txt])
print('trigger', hex(trigger.value))
print('noOfValues', noOfValues.value)
print('usForBlock', usForBlock.value)

# convert ADC counts data to mV
maxADC = ctypes.c_uint16()
status["maxValue"] = pl.pl1000MaxValue(chandle, ctypes.byref(maxADC))
assert_pico_ok(status["maxValue"])
inputRange = 2500
mVValues = adc2mVpl1000(values, inputRange, maxADC)

# close PicoLog 1000 device
# status["closeUnit"] = pl.pl1000CloseUnit(chandle)
# assert_pico_ok(status["closeUnit"])

# display status returns
print(status)

# create time data
# interval = (0.01 * usForBlock.value)/(noOfValues.value * 1)
interval = (0.001 * usForBlock.value) / (noOfValues.value * 1)
print('interval[ms]', interval)

timeMs = np.linspace(0, (noOfValues.value - 1) * interval, noOfValues.value)
print('len(timeMs)', len(timeMs))

# for j in range(noOfValues.value):
#    for i in range(nc):
#        y[i, j] = mVValues[nc * j + i]
# plot data
# plt.plot(timeMs, mVValues[:])
for i in range(nc):
    plt.plot(timeMs + i * interval / nc, y[i, :] * 2.5 / 4096)
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (mV)')
plt.show()
