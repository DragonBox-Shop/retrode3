# Retrode3: User guide

*New web UI development snapshot (November 2026). This document is intended as a starting point for the future public Retrode3 wiki.*

## 1. Connecting

Connect Retrode3 to your computer via USB. On the current development unit, the configured USB network makes the web page available at `http://172.31.255.1/`. This address may change in future releases.

The web interface requires **no password by default**. Owners may optionally enable a password from the device's command line. Do not expose the development interface directly to the public Internet.

## 2. Reading a cartridge

1. Insert a game cartridge into its matching slot or a compatible adapter.
2. Open **Read Cartridge**. Slot cards show the kernel's physical presence indication.
3. If exactly one supported reader matches the occupied slot, it is suggested. **A populated slot does not identify the console or adapter.**
4. Select **Detect cartridge** and review the detected details.
5. Click **Read ROM** and follow the byte-accurate progress indicator.
6. When the job finishes, open **File Manager**.

Do not remove cartridges during a read. Do not blindly try unrelated mappers or voltage settings when detection fails.

## 3. Advanced settings

If the game is not recognized, expand **Advanced settings**. Only installed and supported readers and options are available here. Manually choosing a reader does not identify an adapter or make unsupported electrical modes safe.

The long-term command and progress interface is the centralized `retrode3-cli`, which coordinates the individual OSCR cores and adapters. Availability will change during development.

## 4. File manager and storage

Use **File Manager** to browse, download, rename, move or delete dumped ROMs. The new web-managed storage resides under `/usr/local/games/ROMs/`, with subdirectories such as `ROMs/SNES/`.

The existing Samba share named **retrode** exposes `/usr/local/games`. **Important:** The legacy USB mass-storage image is still independent. Web/Samba files do not automatically appear on the USB mass-storage disk. Never mount the same backing filesystem for simultaneous read/write use by the device and host.

## 5. Wi-Fi settings

Open **General Settings** to view Wi-Fi status, wireless interface name, IP address, available networks and connection controls.

- **Scan networks:** Requests a scan using the installed wireless helper.
- **Connect:** Enter/select an SSID and, if required, a Wi-Fi password.
- **Disconnect:** Ends the current wireless connection. The browser may lose network access.

If the page reports **No Wi-Fi adapter**, use `iw dev` and `ls /sys/class/net` on the device. The original helper uses an old `iwconfig`-based discovery method and can miss an existing device. The new web status checks both the Linux wireless interfaces and `iw dev`. If a device appears but connecting fails, check the helper and backend logs.

SSH diagnostics:

```sh
iw dev
ls /sys/class/net
/usr/local/bin/retrode3-wlan status
service retrode3-web-v2 status
tail -n 50 /var/log/retrode3-web-v2.log
```

## 6. Supported and planned features

- **SNES:** Standard LoROM/HiROM; the web prototype has successfully read a cartridge on real hardware with progress feedback.
- **MegaDrive:** A native standard linear ROM reader has passed separate hardware tests; the shared `retrode3-cli` interface and web integration are still being developed.
- **NES and adapters:** Availability depends on ongoing core and hardware work.
- **Writing:** The write tab is a placeholder. Cartridge, SRAM and flash writing are not available in this web prototype.
- **Detection:** Not every cartridge can be identified automatically; a ROM header is not proof of a database match.

## 7. Source code and further information

- [Retrode3 OS and web interface](https://github.com/DragonBox-Shop/retrode3)
- [OSCR core integration](https://github.com/DragonBox-Shop/retrode3-oscr)
- [Kernel driver](https://github.com/DragonBox-Shop/retrode3-kernel)
- [Hardware and adapters](https://github.com/DragonBox-Shop/retrode3-hardware)

The online guide will eventually live in the Retrode3 wiki. Until then, the Help tab links to this Markdown document.
