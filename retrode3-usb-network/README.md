# Retrode3 USB-NCM bootstrap (first-stage fix)

This package complements, rather than replaces, the generic Letux gadget
implementation. The Letux parent configures the composite gadget and runs
its children. The Retrode3 service is ordered **after** that parent by
SysV-Init's LSB dependency graph.

The `retrode3-usb-network` service:

- Does not touch the UDC, ConfigFS, HID, ACM or Mass Storage.
- Sets `usb0` to `172.31.255.1/30` after the gadget is fully assembled.
- Removes the legacy `192.168.0.202/26` address if present.
- Starts an ISC DHCP server bound only to `usb0`, leasing `172.31.255.2`.
- Does not advertise a default gateway or DNS server **to the host**.
- Configures a **device-side** default route through the USB host,
  `default via 172.31.255.2 dev usb0 metric 203`. This allows the Retrode
  to use the host's internet connection *if* the host enables forwarding/NAT.
  The route alone does not provide internet access.
- Uses a dedicated PID file and lease database.
- Avoids interrupting SSH when the package is installed or removed.

## Hardware test procedure (before merging)

1. On the device: `sh -n /etc/init.d/retrode3-usb-network`.
2. Before testing the service live, stop the **temporary test DHCP server**
   if it is running; do not stop or restart the Letux parent.
3. Start the service: `service retrode3-usb-network start`.
4. On Linux host, verify NetworkManager gets `172.31.255.2/30`
   via DHCP and `ping 172.31.255.1` succeeds.
5. Check USB Mass Storage, HID, ACM and `retrode.local`.
6. Check `ip -4 route` on the Retrode: it must include the USB host as a
   default route. If host forwarding/NAT is enabled, verify internet access
   and DNS from the Retrode. The host must still have no USB default gateway.
7. Reboot with the host connected and repeat all checks.
8. Run `apt upgrade` and verify the configuration survives.

**Known limitation / required upstream follow-up:** The original Letux NCM
child can attempt to configure `192.168.0.202/26` and start a separate DHCP
daemon on some boot paths. This package detects a legacy daemon PID and
refuses to run a conflicting second server. Correct the generic NCM service
lifecycle upstream before treating the integration as production-ready.

The legacy `/etc/network/interfaces.d/letux-usb0` file is owned by
`linux-rootfs-letux-retrode3`. It attempts to load obsolete `g_ether`,
conflicting with the ConfigFS CDC-NCM gadget. On package installation a
local dpkg diversion redirects it to
`/etc/retrode3/letux-usb0.legacy` (outside interfaces.d), so upgrades
to its owning package cannot reactivate it. The diversion is removed
when this package is uninstalled. A previously manually backed-up copy
under `/root/` is not touched.

The FAT backing image used for `START.html` and `START.de.html` is
now staged and swapped atomically by `retrode3-storage-gadget`, rather
than unlinked while still exported. Updated pages become visible after
USB reattachment or reboot.

**Status:** DHCP and automatic connection after reboot have been tested
manually on Retrode hardware. The newly added device-side default route and
Debian package upgrade/diversion need a fresh hardware test.
