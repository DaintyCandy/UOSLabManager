# Third-party notices

UOSLabManager is licensed as a whole under `GPL-3.0-or-later`. Components
listed below remain under their own licenses. The authoritative license text
distributed with each installed package controls if this summary differs from
it. The PyInstaller build specification collects available license and notice
files into the bundled `licenses/` directory.

| Component | Role | License |
| --- | --- | --- |
| PyQt6 | Python Qt bindings | GPL-3.0 or Riverbank Commercial License; this project uses the GPL option |
| Qt 6 | GUI framework used through PyQt6 | LGPL-3.0 and/or GPL-3.0, depending on the Qt module |
| PyQt6-sip | PyQt support module | SIP License and/or GPL variants as distributed |
| pyqtgraph | Plotting and scientific GUI widgets | MIT; some bundled CET color-map data is CC BY 3.0 |
| PyQtDarkTheme (`pyqtdarktheme`) | Qt theme | MIT |
| pySerial | Serial communications | BSD-3-Clause |
| PyVISA | VISA instrument communications | MIT |
| OpenCV / `opencv-python` | Camera capture and image processing | Apache-2.0, with additional third-party notices |
| NumPy | Array processing | BSD-3-Clause, with additional third-party notices |
| Python | Runtime used by binary distributions | Python Software Foundation License |
| PyInstaller | Binary packaging and bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception |

Official licensing references:

- PyQt: <https://riverbankcomputing.com/software/pyqt>
- Qt: <https://doc.qt.io/qt-6/licensing.html>
- pyqtgraph: <https://github.com/pyqtgraph/pyqtgraph>
- PyQtDarkTheme: <https://github.com/5yutan5/PyQtDarkTheme>
- pySerial: <https://github.com/pyserial/pyserial>
- PyVISA: <https://github.com/pyvisa/pyvisa>
- OpenCV: <https://opencv.org/license/>
- NumPy: <https://numpy.org/doc/stable/license.html>
- Python: <https://docs.python.org/3/license.html>
- PyInstaller: <https://pyinstaller.org/en/stable/license.html>

## Equipment manufacturers and interoperability

Equipment manufacturer names and product names are referenced solely for
compatibility identification. They are not project licensors or endorsers.
No manufacturer software, firmware, manuals, logos, or other proprietary
assets are licensed under the UOSLabManager GPL merely because the application
can communicate with the corresponding equipment.

When producing a binary with a different environment, review that exact
environment and update this file if it includes additional or differently
licensed components.
