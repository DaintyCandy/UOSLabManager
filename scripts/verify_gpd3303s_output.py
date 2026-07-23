import argparse
import sys
import time

from plugins.devices.gpd3303s.driver import GPD3303S


def main():
    parser = argparse.ArgumentParser(
        description="Verify low-voltage output on a GW Instek GPD-3303S device."
    )
    parser.add_argument("--port", required=True, help="Serial port for the GPD-3303S device")
    parser.add_argument(
        "--confirm-output-test",
        action="store_true",
        help="Require confirmation before sending OUT1 to the device",
    )
    args = parser.parse_args()

    print("WARNING: CH3 may also be affected by OUT1 on this instrument.")

    if not args.confirm_output_test:
        print("Missing --confirm-output-test; OUT1 will not be sent.")
        return 2

    device = GPD3303S(args.port, output_off_on_connect=False, output_off_on_close=False)
    identified = False
    try:
        try:
            identity = device.identify()
        except ValueError as exc:
            print("Unexpected device identity:", exc)
            return 1

        normalized_identity = identity.upper()
        if "GW INSTEK" not in normalized_identity or "GPD-3303S" not in normalized_identity:
            print("Unexpected device identity:", identity)
            return 1

        identified = True
        print("Identified device:", identity.strip())

        device.output_off()
        initial_status = device.read_status()
        print("Status after OUT0:", initial_status)
        if initial_status["output_on"]:
            print("Expected output to be OFF after OUT0, but output is ON.")
            return 1

        device.set_channel_current("CH1", 0.05)
        device.set_channel_voltage("CH1", 1.0)
        device.set_channel_current("CH2", 0.05)
        device.set_channel_voltage("CH2", 0.0)

        settings = device.read_settings()
        if (
            settings["CH1_voltage_setpoint"] != 1.0
            or settings["CH1_current_setpoint"] != 0.05
            or settings["CH2_voltage_setpoint"] != 0.0
            or settings["CH2_current_setpoint"] != 0.05
        ):
            print("Settings verification failed:", settings)
            return 1

        print("Verified settings before enabling output:", settings)

        print("Enabling output with OUT1...")
        device.output_on()
        time.sleep(2)

        ch1_voltage, ch1_current = device.read_channel_measurement("CH1")
        ch2_voltage, ch2_current = device.read_channel_measurement("CH2")
        status = device.read_status()

        print("Output measurement results:")
        print(f"  CH1: V={ch1_voltage:.3f} V, I={ch1_current:.3f} A")
        print(f"  CH2: V={ch2_voltage:.3f} V, I={ch2_current:.3f} A")
        print("  STATUS:", status)
        return 0
    except Exception as exc:
        print("Error during verification:", exc)
        return 1
    finally:
        print("Disabling output with OUT0...")
        try:
            device.output_off()
        except Exception as exc:
            print("Error while disabling output:", exc)

        if identified:
            try:
                final_status = device.read_status()
                print("Final status after OUT0:", final_status)
                if final_status["output_on"]:
                    print("WARNING: output still ON after OUT0")
            except Exception as exc:
                print("Error while reading final status:", exc)

        try:
            print("Sending final OUT0 before close.")
            device.output_off()
        except Exception as exc:
            print("Error during shutdown:", exc)

        try:
            device.close()
        except Exception as exc:
            print("Error closing device:", exc)


if __name__ == "__main__":
    sys.exit(main())
