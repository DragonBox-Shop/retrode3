# Retrode3 development changelog

These are user-facing changes, not a list of Git commits. Development images
are experimental until hardware testing is complete.

## Unreleased

- Improved root password setup for devices with limited memory, with visible progress and more useful error messages. SSH and public-key controls become available after setup.
- Notifications can now be closed manually and disappear automatically after 12 seconds.

- Reduced empty space on the reader page and removed unnecessary outer panel scrollbars while keeping the layout steady.

- USB networking now uses a fixed device address (172.31.255.1) and immediately offers DHCP to the computer, without changing its Internet gateway or DNS. Wi-Fi obtains its network settings independently.
- Updated the USB welcome pages to match the fixed address and explain browser HTTP warnings.

## 2026.11.26-rc3

- The cartridge reader page keeps its layout steady when cartridges are inserted,
  detected or read. Read progress has a dedicated area below the slots, and
  cartridge information and ROM results have reserved space.
- If a cartridge is not recognized, the relevant disabled plugins are suggested.
  The plugin manager can be opened directly with the affected slot selected.
- Wi-Fi scanning and connection now show what is happening, including waiting
  for an IP address and confirmation when connected.
- Developer passwords no longer require a minimum of 12 characters. Choose a
  non-empty password. SSH remains disabled until explicitly enabled.
- Add or remove SSH public keys in the developer settings for passwordless SSH
  login. Existing password login remains available.
- Fixed access to the web interface through /index.html.
- Development image downloads include SHA256 checksums and this changelog.

## 2026.11.26-rc2

- First downloadable development SD image based on a fresh, minimal Debian 12
  system, with a lighter web server and reduced memory requirements.
- USB networking, the read-only welcome drive and USB serial console are
  available independently of SSH.
- Wi-Fi can be scanned and configured from the web interface; configured
  networks are saved for reconnecting after reboot.
- Read progress and completed ROM information are associated with their
  cartridge slot. Other cartridge operations are blocked while the hardware
  is busy.
- Optional developer SSH access can be enabled from the web interface.
- Includes the existing cartridge reading and supported flash-writing tools.
- Known limitation: direct access to /index.html can return Forbidden; use
  the root URL instead.

The ESP32-C6 firmware update is not included in these downloads. USB game
controller support is still under development.
