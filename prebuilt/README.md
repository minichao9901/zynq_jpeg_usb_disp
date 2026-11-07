# Unrestricted RGB/JPEG release pairs

The RTL branch delivers `jpeg-rtl/` and `rgb-rtl/`, each with a matched BIT,
ELF, HDF, PS init and SHA-256 manifest. They share the RTL JPEG design and differ
in default USB encoding. Use `python tools/flash.py jpeg --dry-run` or
`python tools/flash.py rgb --dry-run` for offline package verification.
The pairs below are the earlier board-validated NEON builds.

| Default Windows encoding | BIT | ELF | Download |
| --- | --- | --- | --- |
| RGB565 | `rgb/usb_display.bit` | `rgb/usb_display.elf` | `python tools/flash.py rgb --legacy` |
| JPEG | `jpeg/usb_display.bit` | `jpeg/usb_display.elf` | `python tools/flash.py jpeg --legacy` |

Each directory also contains its paired `ps7_init.tcl`, `system.hdf`, and
`manifest.json` with SHA-256 values, source/build inputs, and runtime build ID.
Both ELFs retain support for both wire encodings; they differ in their compiled
default/preferred encoding. The CLI selects the corresponding host configuration.

The BIT files are byte-identical because both modes use the same unchanged LCD
PL. They are intentionally included in both self-contained pairs. The ELFs are
different and report their mode/build identity through vendor request 0x34.
The current profiles keep MM2S running and use frame-boundary shadow updates.
Five software buffers protect scanout/retired readers and allow replacement of
old queued frames. The CLI rejects older stop/start display profiles and checks
live frame-boundary progress through vendor request 0x35.
Git newline conversion is disabled in `prebuilt/` so the PS init script's
SHA-256 remains stable when checking out the committed package on Windows.

Both profiles use `Fps999` and default to normal processing without FNV. The
reference IDD bypasses its low-FPS frame dropping when the value is >=50; this
does not impose a 999fps processing target. Actual rates depend on USB,
decoding, desktop changes, and the display refresh path.

`usb_display.bit`, `system.hdf`, and `ps7_init.tcl` at this directory's root are
shared hardware inputs. The root `usb_display.elf` remains a byte-identical JPEG
compatibility alias; new downloads should always use `tools/flash.py` and the
explicit mode directories. The root `manifest.json` indexes both packages.

The CLI uses JTAG/RAM, verifies hashes before loading, updates the driver's
registry override, verifies firmware identity and the received frame type, and
restores extended desktop mode preserving the original primary monitor. It does
not write QSPI.
