#
# Copyright (C) 2019 Pico Technology Ltd. See LICENSE file for terms.
#
# PL1000 SINGLE MODE EXAMPLE
# This example opens a pl1000 device, sets up the device for capturing data from channel 1.
# Then this example collect a sample from channel 1 and displays it on the console.

import ctypes
import numpy as np

from picosdk.errors import ClosedDeviceError
from picosdk.pl1000 import pl1000 as pl
import matplotlib.pyplot as plt
from picosdk.functions import adc2mVpl1000, assert_pico_ok
from time import sleep, time


class PicoLog1000:
    def __init__(self):
        self.handle = None
        self.opened = False
        self.channels = []
        self.sampling = None
        self.trigger = None
        self.data = None

    # def __del__(self):
    #     pass

    def open(self):
        self.handle = ctypes.c_int16()
        stat = pl.pl1000OpenUnit(ctypes.byref(self.handle))
        assert_pico_ok(stat)
        self.opened = True

    def assert_open(self):
        if not self.opened:
            raise ClosedDeviceError("PicoLog is not opened")
        # handle = ctypes.c_int16()
        # progress = ctypes.c_int16()
        # complete = ctypes.c_int16()
        # stat = pl.pl1000OpenUnitProgress(ctypes.byref(handle), ctypes.byref(progress), ctypes.byref(complete))
        # assert_pico_ok(stat)
        # print('progress', handle, progress.value, complete.value)

    def get_info(self):
        self.assert_open()
        self.info = (ctypes.c_int8 * 10)()
        length = ctypes.c_int16(10)
        #stat = pl.pl1000GetUnitInfo(self.handle, None, length, ctypes.byref(length), INFO)
        #assert_pico_ok(stat)

    def set_channels(self, cnls=None):
        self.assert_open()
        if cnls is None:
            pass
        pass


# Create chandle and status ready for use
chandle = ctypes.c_int16()
status = {}

# open PicoLog 1000 device
txt = "openUnit"
print('---', txt)
t0 = time()
status[txt] = pl.pl1000OpenUnit(ctypes.byref(chandle))
print('elapsed time', time() - t0, 's')
print(txt, 'status', status[txt])
assert_pico_ok(status[txt])

p1 = ctypes.c_int16(1000)
p2 = ctypes.c_int8(50)
p3 = ctypes.c_int16()
#stat = pl.pl1000OpenUnitProgress(ctypes.byref(p1), ctypes.byref(p2), ctypes.byref(p3))
#print('progress', handle, chandle, progress.value, complete.value)
#stat = pl.pl1000OpenUnitAsync(ctypes.byref(handle))
#stat = pl.pl1000PingUnit(chandle)
stat = pl.pl1000SetPulseWidth(chandle, p1, p2)
assert_pico_ok(stat)

# length = ctypes.c_int16(10)
# info = (ctypes.c_int8 * length.value)()
# stat = pl.pl1000GetUnitInfo(chandle, None, length, ctypes.byref(length), pl.PICO_INFO['PICO_DRIVER_VERSION'])
# assert_pico_ok(stat)
# info = (ctypes.c_int8 * length.value)()
# stat = pl.pl1000GetUnitInfo(chandle, ctypes.byref(info), length, ctypes.byref(length), pl.PICO_INFO['PICO_DRIVER_VERSION'])
# assert_pico_ok(stat)

dt_us = 8000
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
t0 = time()
status[txt] = pl.pl1000SetInterval(chandle, ctypes.byref(usForBlock), noOfValues, ctypes.byref(channels), nc)
print('elapsed time', time() - t0, 's')
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
t0 = time()
status[txt] = pl.pl1000Run(chandle, noOfValues, mode)
print(txt, 'status', status[txt])
assert_pico_ok(status[txt])
print('elapsed time', time() - t0, 's')
print('noOfValues', noOfValues.value)
print('usForBlock', usForBlock.value)

print('')
print('--- wait ---')

# sleep(usForBlock.value / 1000000 + 0.5)

while not ready.value:
    # print('*')
    assert_pico_ok(pl.pl1000Ready(chandle, ctypes.byref(ready)))
print('elapsed time', time() - t0, 's')
print('noOfValues', noOfValues.value)
print('usForBlock', usForBlock.value)

values = (ctypes.c_uint16 * (noOfValues.value * nc))()
oveflow = ctypes.c_uint16()
trigger = ctypes.c_uint32()
print('len(values)', len(values), noOfValues.value)

txt = "getValues"
print('---', txt)
t0 = time()
status[txt] = pl.pl1000GetValues(chandle, ctypes.byref(values), ctypes.byref(noOfValues), ctypes.byref(oveflow),
                                 ctypes.byref(trigger))
y = np.zeros((nc, noOfValues.value), dtype=np.uint16, order='F')
st = pl.pl1000GetValues(chandle, y.ctypes, ctypes.byref(noOfValues), ctypes.byref(oveflow), ctypes.byref(trigger))
assert_pico_ok(st)
print('status', txt, status[txt])
print('elapsed time', time() - t0, 's')
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
status["closeUnit"] = pl.pl1000CloseUnit(chandle)
assert_pico_ok(status["closeUnit"])

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
