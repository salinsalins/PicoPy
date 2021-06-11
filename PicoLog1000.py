import time
import ctypes
import logging

import numpy as np

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
        self.logger.debug('Device opened')

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

    def get_info(self, info=pl1000.PICO_INFO["PICO_HARDWARE_VERSION"]):
        self.assert_open()
        length = ctypes.c_int16(10)
        info_str = {}
        for i in pl1000.PICO_INFO:
            info_str[i] = ''
            v = pl1000.PICO_INFO[i]
            try:
                self.last_status = pl1000.pl1000GetUnitInfo(self.handle, None, length,
                                                            ctypes.byref(length), v)
                out_info = (ctypes.c_int8 * length.value)()
                self.last_status = pl1000.pl1000GetUnitInfo(self.handle, out_info, length.value,
                                                            ctypes.byref(length), v)
                assert_pico_ok(self.last_status)
                for j in range(len(out_info)-1):
                    info_str[i] += chr(out_info[j])
            except:
                pass
        self.info = info_str
        return self.info

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
        self.delta_t = t_us.value
        self.sampling = (0.001 * self.delta_t) / self.points
        self.logger.debug('%s channels %s; sampling %s ms; %s points; duration %s us',
                          len(self.channels), self.channels, self.sampling, self.points, self.delta_t)
        # create array for data
        self.data = np.empty((nc, self.points), dtype=np.uint16, order='F')
        t = np.linspace(0, (self.points - 1) * self.sampling, self.points)
        self.times = np.empty(self.data.shape)
        for i in range(nc):
            self.times[i, :] = t + (i * self.sampling / len(self.channels))
        if self.delta_t != channel_record_us or self.points != channel_points:
            self.logger.warning('Time interval has been corrected from %s to %s us',
                                channel_record_us, self.delta_t)
            return False
        return True

    def run(self, n_values=None, mode=pl1000.PL1000_BLOCK_METHOD["BM_SINGLE"], wait=False):
        # start streaming
        self.assert_open()
        if n_values is None:
            n = ctypes.c_uint32(self.points)
        elif not isinstance(n_values, ctypes.c_uint32):
            n = ctypes.c_uint32(n_values)
        else:
            n = n_values
        self.last_status = pl1000.pl1000Run(self.handle, n, mode)
        assert_pico_ok(self.last_status)
        if wait:
            self.ready(True)

    def ready(self, wait=False, timeout=None):
        self.assert_open()
        t0 = time.time()
        ready = ctypes.c_int16(0)
        self.last_status = pl1000.pl1000Ready(self.handle, ctypes.byref(ready))
        if wait:
            if self.timeout is not None and timeout is None:
                timeout = self.timeout
            while not ready.value:
                # print('*')
                if timeout is not None and time.time() - t0 > timeout:
                    break
                self.last_status = pl1000.pl1000Ready(self.handle, ctypes.byref(ready))
            assert_pico_ok(self.last_status)
        assert_pico_ok(self.last_status)
        return ready.value

    def wait_result(self, timeout=None):
        return self.ready(True, timeout)

    def read(self, wait=False):
        self.assert_open()
        if wait:
            self.ready(True)
        if not self.ready():
            self.logger.warning('Read on not ready device')
        overflow = ctypes.c_uint16()
        trigger = ctypes.c_uint32()
        n = ctypes.c_uint32(self.points)
        self.last_status = pl1000.pl1000GetValues(self.handle, self.data.ctypes, ctypes.byref(n),
                                                  ctypes.byref(overflow), ctypes.byref(trigger))
        assert_pico_ok(self.last_status)
        self.overflow = overflow.value
        self.trigger = trigger.value
        if self.points != n.value:
            self.logger.warning('Data partial reading %s of %', n.value, self.points)

    def close(self):
        self.last_status = pl1000.pl1000CloseUnit(self.handle)
        assert_pico_ok(self.last_status)

    def stop(self):
        self.assert_open()
        self.last_status = pl1000.pl1000Stop(self.handle)
        assert_pico_ok(self.last_status)

    def set_trigger(self, enabled=False, channel=pl1000.PL1000Inputs["PL1000_CHANNEL_1"], edge=0,
                    threshold=2048, hysteresis=100, delay_percent=10.0, auto_trigger=False, auto_ms=1000):
        self.assert_open()
        self.last_status = pl1000.pl1000SetTrigger(self.handle, ctypes.c_uint16(enabled),
                                                   ctypes.c_uint16(auto_trigger), ctypes.c_uint16(auto_ms),
                                                   ctypes.c_uint16(channel), ctypes.c_uint16(edge),
                                                   ctypes.c_uint16(threshold), ctypes.c_uint16(hysteresis),
                                                   delay_percent)
        assert_pico_ok(self.last_status)

    def ping(self):
        t0 = time.time()
        self.last_status = pl1000.pl1000PingUnit(self.handle)
        if self.last_status == pl1000.PICO_STATUS['PICO_OK']:
            return time.time() - t0
        else:
            return -1.0


if __name__ == "__main__":
    pl = PicoLog1000()
    pl.open()
    pl.set_timing([1, 2], 100000, 2000000)
    print(pl.ping())
    pl.run()
    pl.wait_result()
    pl.read()
    pl.close()

    import matplotlib.pyplot as plt
    for i in range(len(pl.channels)):
        plt.plot(pl.times[i, :], pl.data[i, :] * pl.scale * 1000)
    plt.xlabel('Time (ms)')
    plt.ylabel('Voltage (mV)')
    plt.legend([str(i) for i in pl.channels])
    plt.show()
