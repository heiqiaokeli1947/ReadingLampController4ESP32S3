"""水泵控制状态机：一级散热。
传感器：LM75A 0x4F（灯板温度）。
水泵串联在灯板与水冷散热器之间，关灯后仍继续循环带走灯板余热，
直到灯板温度降到 LEDLThreshold 以下才停转（停机完全由温度决定）。
继承自 ThermalControlFSM，差异点通过 params 注入。"""

from domain.ThermalControlFSM import ThermalControlFSM


class FSM(ThermalControlFSM):

    def __init__(self, bspInstance, config):
        super().__init__(bspInstance, config, {
            "name": "Pump",
            "temp_getter": lambda: bspInstance.getSensorData().LM75LedTemp,
            "h_key": "LEDHThreshold",
            "l_key": "LEDLThreshold",
            "pwm_ch": "pumpPwm",
            "pwm_prefix": "pumpPwm",
            "stop_when_light_off": False,       # 不判断灯光，关灯后继续降温
            "run_time_db_key": "pumpTotalRunTime",
            "speed_key": "pumpSpeed",
            "temp_key": "ledTemp",
        })
