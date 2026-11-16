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
- Does not advertise a default gateway or DNS server to the host.
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
6. Reboot with the host connected and repeat all checks.
7. Run `apt upgrade` and verify the configuration survives.

**Known limitation / required upstream follow-up:** The original Letux NCM
child can attempt to configure `192.168.0.202/26` and start a separate DHCP
daemon on some boot paths. This package detects a legacy daemon PID and
refuses to run a conflicting second server. Correct the generic NCM service
lifecycle upstream before treating the integration as production-ready.

The legacy `/etc/network/interfaces.d/letux-usb0` file must also be
disabled or removed in the final image; it is an obsolete `g_ether` setup.
Its ownership/diversion strategy is intentionally deferred to the
upstream integration, rather than silently editing another package's files.

**Status:** proposed, not yet hardware-tested.
