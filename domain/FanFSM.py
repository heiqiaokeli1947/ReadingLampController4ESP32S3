"""风扇控制状态机：二级散热。
传感器：LM75A 0x4A（水冷散热器出水口侧温度）。
风扇属二级散热：只有散热器被动放热不足、出水口温度超阈值时才启动。
关灯后立即停转（风扇噪音大），余热由水泵单独循环处理。
继承自 ThermalControlFSM，差异点通过 params 注入。"""

from domain.ThermalControlFSM import ThermalControlFSM


class FSM(ThermalControlFSM):

    def __init__(self, bspInstance, config):
        super().__init__(bspInstance, config, {
            "name": "Fan",
            "temp_getter": lambda: bspInstance.getSensorData().LM75FanTemp,
            "h_key": "fanHThreshold",
            "l_key": "fanLThreshold",
            "pwm_ch": "fanPwm",
            "pwm_prefix": "fanPwm",
            "stop_when_light_off": True,        # 关灯即停
            "run_time_db_key": "fanTotalRunTime",
            "speed_key": "fanSpeed",
            "temp_key": "fanTemp",
        })
