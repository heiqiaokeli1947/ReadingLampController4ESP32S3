# MIT License (MIT)
# Copyright (c) 2020 Mike Teachman
# https://opensource.org/licenses/MIT

# Platform-specific MicroPython code for the rotary encoder module
# ESP8266/ESP32 implementation

# Documentation:
#   https://github.com/MikeTeachman/micropython-rotary

import os
from machine import Pin
from lib.rotary.rotary import Rotary
from sys import platform

# ESP32 (WROOM-32) 的 GPIO34-39 为输入专用脚，不支持输出/中断上下拉
# ESP32-S3 的 GPIO34-48 均为通用 IO，无此限制
_esp32_deny_pins = [34, 35, 36, 37, 38, 39]
_is_s3 = 'ESP32-S3' in os.uname().machine


class RotaryIRQ(Rotary):

    def __init__(self, pin_num_clk, pin_num_dt, min_val=0, max_val=10, incr=1,
                 reverse=False, range_mode=Rotary.RANGE_UNBOUNDED, pull_up=True, half_step=False, invert=False):
        print("RotaryIRQ init:{} s3={}".format(platform, _is_s3))
        if platform == 'esp32' and not _is_s3:
            if pin_num_clk in _esp32_deny_pins:
                raise ValueError(
                    '%s: Pin %d not allowed. Not Available for Interrupt: %s' %
                    (platform, pin_num_clk, _esp32_deny_pins))
            if pin_num_dt in _esp32_deny_pins:
                raise ValueError(
                    '%s: Pin %d not allowed. Not Available for Interrupt: %s' %
                    (platform, pin_num_dt, _esp32_deny_pins))

        super().__init__(min_val, max_val, incr, reverse, range_mode, half_step, invert)

        if pull_up == True:
            print('Pull-up enabled on pins %d and %d' % (pin_num_clk, pin_num_dt))
            self._pin_clk = Pin(pin_num_clk, Pin.IN, Pin.PULL_UP)
            self._pin_dt = Pin(pin_num_dt, Pin.IN, Pin.PULL_UP)
        else:
            self._pin_clk = Pin(pin_num_clk, Pin.IN)
            self._pin_dt = Pin(pin_num_dt, Pin.IN)

        self._enable_clk_irq(self._process_rotary_pins)
        self._enable_dt_irq(self._process_rotary_pins)

    def _enable_clk_irq(self, callback=None):
        self._pin_clk.irq(
            trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
            handler=callback)

    def _enable_dt_irq(self, callback=None):
        self._pin_dt.irq(
            trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
            handler=callback)

    def _disable_clk_irq(self):
        self._pin_clk.irq(handler=None)

    def _disable_dt_irq(self):
        self._pin_dt.irq(handler=None)

    def _hal_get_clk_value(self):
        return self._pin_clk.value()

    def _hal_get_dt_value(self):
        return self._pin_dt.value()

    def _hal_enable_irq(self):
        self._enable_clk_irq(self._process_rotary_pins)
        self._enable_dt_irq(self._process_rotary_pins)

    def _hal_disable_irq(self):
        self._disable_clk_irq()
        self._disable_dt_irq()

    def _hal_close(self):
        self._hal_disable_irq()
