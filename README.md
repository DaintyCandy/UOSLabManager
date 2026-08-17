# UOSLabManager

UOSLabManager is a desktop application for operating laboratory instruments,
monitoring measurements, and running experiment workflows.

## Installation

Create a Python environment, install the dependencies, and run the application:

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Sequence architecture

Sequence recipes are validated and executed by the Qt-independent
`core.sequence_engine.SequenceEngine`. The sequence panel is an editor and Qt
adapter only; it starts the engine on a worker thread so waits and instrument
commands do not freeze the interface.

Device sequence commands are declared by each `DevicePlugin` with
`SequenceCommand` metadata (label, unit, range, choices, and executor). Adding a
command therefore does not require editing `gui/panel_sequence.py`. Executors
receive `(device, value, context)`; the context provides cancellation-aware
waiting, logging, and per-run state.

## Building the Windows executable

```powershell
python -m PyInstaller --noconfirm UOSLabManager.spec
```

Do not publish the generated executable by itself. A binary release must also
provide the complete corresponding source for that exact build, including this
repository's build specification and dependency information, under the same
GPL terms. The build embeds `LICENSE`, `THIRD_PARTY_NOTICES.md`, and available
license files from the installed Python distributions.

## License

Copyright (C) 2026 UOSLabManager contributors.

The original UOSLabManager source code is free software licensed under the
[GNU General Public License, version 3 or later](LICENSE), identified by the
SPDX expression `GPL-3.0-or-later`.

The application is distributed without any warranty, including implied
warranties of merchantability or fitness for a particular purpose. See the
GPL for the complete terms.

Third-party libraries and data remain under their respective licenses. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A GPL license for this
repository does not relicense third-party components, device firmware,
manufacturer software, manuals, logos, or trademarks.

## Device and trademark notice

This is an independent interoperability project. Product and company names
are used only to identify compatible equipment. The project is not affiliated
with, endorsed by, or sponsored by the equipment manufacturers. Do not add
manufacturer binaries, manuals, firmware, logos, or other proprietary assets
to this repository unless redistribution permission has been documented.
