import pyvisa


class Keithley2400:
    def __init__(self, resource_name):
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(resource_name)
        self.inst.timeout = 5000
        self.inst.write_termination = "\n"
        self.inst.read_termination = "\n"

    def close(self):
        try:
            self.output_off()
        finally:
            self.inst.close()
            self.rm.close()

    def write(self, command):
        self.inst.write(command)

    def query(self, command):
        return self.inst.query(command).strip()

    def idn(self):
        return self.query("*IDN?")

    def reset(self):
        self.write("*RST")

    def output_on(self):
        self.write(":OUTP ON")

    def output_off(self):
        self.write(":OUTP OFF")

    def set_voltage_source(self, voltage, current_limit=0.01):
        self.write(":SOUR:FUNC VOLT")
        self.write(":SOUR:VOLT:MODE FIX")
        self.write(f":SOUR:VOLT {voltage}")
        self.write(":SENS:FUNC 'CURR'")
        self.write(f":SENS:CURR:PROT {current_limit}")

    def set_current_source(self, current, voltage_limit=10):
        self.write(":SOUR:FUNC CURR")
        self.write(":SOUR:CURR:MODE FIX")
        self.write(f":SOUR:CURR {current}")
        self.write(":SENS:FUNC 'VOLT'")
        self.write(f":SENS:VOLT:PROT {voltage_limit}")

    def set_nplc(self, value):
        self.write(f":SENS:VOLT:NPLC {value}")
        self.write(f":SENS:CURR:NPLC {value}")

    def set_remote_sense(self, enabled):
        self.write(f":SYST:RSEN {'ON' if enabled else 'OFF'}")

    @staticmethod
    def _clean_function(value):
        return value.replace('"', "").replace("'", "").strip().upper()

    def read_monitoring(self):
        values = self.query(":READ?").split(",")
        if len(values) < 2:
            raise ValueError(f"Unexpected READ response: {values!r}")
        voltage = float(values[0])
        current = float(values[1])
        resistance = float(values[2]) if len(values) > 2 else float("nan")
        condition = int(float(self.query(":STAT:MEAS:COND?")))
        source_mode = self._clean_function(self.query(":SOUR:FUNC?"))
        output_on = self.query(":OUTP?").strip() in {"1", "ON"}
        error = self.query(":SYST:ERR?")
        return {
            "voltage_V": voltage,
            "current_A": current,
            "power_W": voltage * current,
            "resistance_Ohm": resistance,
            "source_mode": source_mode,
            "output_on": output_on,
            "compliance": bool(condition & (1 << 14)),
            "ovp": bool(condition & (1 << 13)),
            "communication_error": not error.startswith("0,"),
            "error": "" if error.startswith("0,") else error,
            "measurement_condition": condition,
        }

    def read_settings(self):
        mode = self._clean_function(self.query(":SOUR:FUNC?"))
        source_key = "VOLT" if mode.startswith("VOLT") else "CURR"
        compliance_key = "CURR" if source_key == "VOLT" else "VOLT"
        return {
            "source_mode": source_key,
            "source_level": float(self.query(f":SOUR:{source_key}?")),
            "compliance": float(self.query(f":SENS:{compliance_key}:PROT?")),
            "output": self.query(":OUTP?").strip() in {"1", "ON"},
            "nplc": float(self.query(f":SENS:{compliance_key}:NPLC?")),
            "remote_sense": self.query(":SYST:RSEN?").strip() in {"1", "ON"},
        }

    def read_all(self):
        try:
            return self.read_monitoring()
        except Exception as error:
            return {"error": str(error), "communication_error": True}

    def measure_voltage(self):
        return float(self.query(":MEAS:VOLT?"))

    def measure_current(self):
        return float(self.query(":MEAS:CURR?"))

    def measure_resistance(self):
        return float(self.query(":MEAS:RES?"))
