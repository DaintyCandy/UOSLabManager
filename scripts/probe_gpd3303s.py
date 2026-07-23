import argparse
import serial


def main():
    parser = argparse.ArgumentParser(description="Probe a GPD-3303S by sending only *IDN? and reading identity.")
    parser.add_argument("--port", required=True, help="Serial port for the GPD-3303S device")
    parser.add_argument("--write-terminator", default="\\n", help="Command terminator to append to sent commands")
    parser.add_argument("--read-terminator", default="\\r", help="Response terminator to use for incoming data")
    args = parser.parse_args()

    write_terminator = args.write_terminator.replace("\\r", "\r").replace("\\n", "\n")
    read_terminator = args.read_terminator.replace("\\r", "\r").replace("\\n", "\n")

    ser = serial.Serial(
        port=args.port,
        baudrate=9600,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=2.0,
        xonxoff=False,
        rtscts=False,
    )
    try:
        ser.write(("*IDN?" + write_terminator).encode("ascii"))
        response = ser.read_until(expected=read_terminator.encode("ascii") if read_terminator else None)
        if not response:
            raise TimeoutError("No response to *IDN?")
        text = response.decode("ascii", errors="replace")
        if read_terminator and text.endswith(read_terminator):
            text = text[: -len(read_terminator)]
        print(text.strip())
    finally:
        ser.close()


if __name__ == "__main__":
    main()
