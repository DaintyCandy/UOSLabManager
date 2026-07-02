import pyvisa


class Keithley2400:
    #gpib 공통 함수
    def __init__(self, resource_name):
        self.rm = pyvisa.ResourceManager()

        self.inst = self.rm.open_resource(resource_name)

        self.inst.timeout = 5000
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"

    def close(self):
        self.inst.close()
        self.rm.close()

    def write(self, cmd):
        self.inst.write(cmd)

    def query(self, cmd):
        return self.inst.query(cmd).strip()

    def idn(self):
        return self.query("*IDN?")

    def reset(self):
        self.write("*RST")

    def output_on(self):
        self.write(":OUTP ON")

    def output_off(self):
        self.write(":OUTP OFF")
    #keithley2400기능관련함수
    def set_voltage_source(self,
                           voltage,
                           current_limit=0.01):#전압소스모드

        self.write(":SOUR:FUNC VOLT")
        self.write(f":SOUR:VOLT {voltage}")
        self.write(f":SENS:CURR:PROT {current_limit}")

    def set_current_source(self,
                           current,
                           voltage_limit=10):#전류소스모드

        self.write(":SOUR:FUNC CURR")
        self.write(f":SOUR:CURR {current}")
        self.write(f":SENS:VOLT:PROT {voltage_limit}")

    def measure_voltage(self):#전압측정

        self.write(":SENS:FUNC 'VOLT'")

        return float(
            self.query(":MEAS:VOLT?")
        )

    def measure_current(self):#전류측정

        self.write(":SENS:FUNC 'CURR'")

        return float(
            self.query(":MEAS:CURR?")
        )

    def measure_resistance(self):#저항측정

        self.write(":SENS:FUNC 'RES'")

        return float(
            self.query(":MEAS:RES?")
        )

    def read_all(self):#한 번에 읽어오

        values = self.query(":READ?")

        vals = values.split(",")

        return {
            "voltage_V": float(vals[0]),
            "current_A": float(vals[1]),
            "resistance_Ohm": float(vals[2]),
        }