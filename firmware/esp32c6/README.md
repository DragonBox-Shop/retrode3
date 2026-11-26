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

## Guarded automatic recovery (development)

After physical validation, enable the SysV recovery service in the image.
The package itself does not register or start the service. An explicit
root-owned `/etc/retrode3/esp-autorepair-enabled` marker is required during
validation. Compatible firmware is untouched; the known NG-1.0.3.0.1
mismatch triggers an update; missing SDIO firmware triggers a read-only
ROM MD5 check over the entire 4 MiB flash and writes only if erased.
Other nonblank or unrecognized firmware is left untouched for diagnosis.
One persistent attempt per bundled firmware prevents repeated writes after
power loss or failure. A successful write is not proof of WLAN registration.

Use `--probe-blank` for a read-only flash-content check (it resets the ESP
and temporarily unbinds its WLAN SDIO controller). No automatic customer
flash until recovery, license, package and hardware checks are completed.

## Hardware test, 2026-11-26

Kernel commit 1377dda6fb2c819541d67ff417f02b569de07137 fixes the SDIO
unbind hang with NG-1.0.3.0.1. All four image writes passed MD5, then the
ROM rejected FLASH_END. Cold boot registered NG-1.0.6.0.1 and WLAN scan
worked. The revised flasher reports each verified partition, warns on
FLASH_END failure after verified writes, resets and attempts SDIO rebind.
Hot rebind and the revised executable still require hardware validation.
Use --verify-installed to compare all four installed regions by ROM MD5
without erasing/programming; this temporarily disconnects WLAN. Do not
reflash the working device simply to test the error path.
