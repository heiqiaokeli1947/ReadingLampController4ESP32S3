__version__ = '0.0.3'

from micropython import const

# registers
_LM75A_TEMP = const(0x00) # Temperature register (r) 16-bit
_LM75A_CONF = const(0x01) # Configuration register (r/w) 8-bit, default: enabled, comparator, os active low, single fault
_LM75A_THYST = const(0x02) # Hysteresis register (r/w) 16-bit, default: 75°C
_LM75A_TOS = const(0x03) # Overtemperature shutdown register (r/w) 16-bit, default: 80°C

class LM75A:
    def __init__(self, i2c, address=0x48):
        self._i2c = i2c
        self._address = address # 0x48-0x4F
        self._config = 0x00
        self._buf1 = bytearray(1)
        self._buf2 = bytearray(2)
        self.check()
        self.config()
    def check(self):
        if self._i2c.scan().count(self._address) == 0:
            raise OSError('LM75A not found at I2C address {:#x}'.format(self._address))
    def config(self, shutdown=None, os_mode=None, os_polarity=None, os_fault_queue=None):
        # 修复：原实现仅在 os_fault_queue 不为 None 时才写寄存器，
        # 导致单独设置 shutdown/os_mode/os_polarity 时配置不生效。
        # 改为：只要有任一参数非 None，就更新 _config 并写入硬件。
        changed = False
        if shutdown is not None:
            self._config = (self._config & ~1) | (shutdown & 1)
            changed = True
        if os_mode is not None:
            self._config = (self._config & ~2) | ((os_mode << 1) & 2)
            changed = True
        if os_polarity is not None:
            self._config = (self._config & ~4) | ((os_polarity << 2) & 4)
            changed = True
        if os_fault_queue is not None:
            self._config = (self._config & ~24) | ((os_fault_queue << 3) & 24)
            changed = True
        if changed:
            self._buf1[0] = self._config
            self._i2c.writeto_mem(self._address, _LM75A_CONF, self._buf1)
    def temp(self):
        self._i2c.readfrom_mem_into(self._address, _LM75A_TEMP, self._buf2)
        val = (self._buf2[0] << 3) | (self._buf2[1] >> 5)
        return self._twos_comp(val, 11) * 0.125
    def tos(self, temp):
        self._temp_to_9bit_reg(temp)
        self._i2c.writeto_mem(self._address, _LM75A_TOS, self._buf2)
    def thyst(self, temp):
        self._temp_to_9bit_reg(temp)
        self._i2c.writeto_mem(self._address, _LM75A_THYST, self._buf2)
    def _twos_comp(self, val, bits):
        mask = 2 ** (bits - 1)
        return -(val & mask) + (val & ~mask)
    def _rev_twos_comp(self, val, bits):
        return val & ((1 << bits) -1)
    def _temp_to_9bit_reg(self, temp):
        val = self._rev_twos_comp(int(temp / 0.5), 9)
        self._buf2[0] = val >> 1
        self._buf2[1] = val << 7