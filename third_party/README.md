# libjpeg-turbo 3.1.2

Source: https://github.com/libjpeg-turbo/libjpeg-turbo/tree/3.1.2

Pinned source archive downloaded from the project's GitHub API on 2026-11-06.
The vendored source is unmodified; Java, test images, external test/fuzz data,
and documentation output directories were omitted. Required release/CMake
templates and all library/SIMD source are included.

Licenses: [LICENSE.md](libjpeg-turbo/LICENSE.md),
[README.ijg](libjpeg-turbo/README.ijg), and notices in individual source files.

**This software is based in part on the work of the Independent JPEG Group.**

Build: Cortex-A9, ARMv7 hard-float, Neon SIMD, static libjpeg API. The TurboJPEG
API, filesystem tools, Java, arithmetic coding, and OS TLS are disabled. Decode
runs on one bare-metal CPU; no dynamic CPU/OS feature probing is needed.

This dependency applies to the legacy NEON builds. The
`lcd-continuous-20261106` tag contains their firmware build script.
The matching packages and historical source/library SHA-256 values are
in `prebuilt/jpeg/` and `prebuilt/rgb/`. The current RTL build uses the
decoder sources in `fpga/jpeg/`.
