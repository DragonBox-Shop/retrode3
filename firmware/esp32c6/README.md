# Retrode3 ESP32-C6 firmware candidate

Imported from Nikolaus's `esp-serial-flasher-HEAD-42a551d.tar.gz`.
Archive SHA256: `5fd6e3fd4a4c5f7439875e315d3f866c82961b61c790aa37913b6b886c8b9d21`.
The vendor library and Letux reference implementation are preserved in
`vendor/`. Only the UART library is compiled; unrelated examples are not
included. The four firmware files are byte-identical to the supplied files;
see `firmware/NOTES` and `firmware/SHA256SUMS`.

Firmware release NG-1.0.6.0.1, ESP-Hosted 84d7e4c, ESP-IDF fcae32885.
The current Retrode3 kernel driver expects that exact version. The currently
installed NG-1.0.3.0.1 firmware is incompatible. Confirm distribution rights
for the supplied binary firmware before publishing to a public repository
or shipping it to customers. The flasher library's Apache-2.0 license is
retained; it is not by itself a license for the firmware binary.

## Status: staging only

Do not flash automatically on boot, install, upgrade, or image creation.
The original Letux example has unchecked write results and is not the
production executable. `make check` verifies the supplied firmware files;
`make` builds the Retrode3 candidate; `make package` builds an unpublished
MIPSEL .deb with explicit user-triggered flash command only. No maintainer
scripts. Use a Debian 12 mipsel-linux-gnu toolchain for a target build.

Before image/release integration: verify /dev/ttyS1 mapping, confirm flash
backup/recovery with Nikolaus (a replacement SD is not a firmware rollback),
review the candidate serial/reset code, run hardware tests and verify WLAN
registration after a cold boot. Do not use it on a customer's device before
this gate. The new executable refuses to flash without an explicit argument,
checks each file and target, verifies each partition with MD5 and stops on
error. A partial update can still leave the ESP unbootable. No firmware readback
or backup is implemented by this candidate. Only use the documented board
and physical recovery setup.
