# Retrode3 USB mass-storage quick-start

The virtual USB drive is built from the two tracked, offline HTML files:

- `media/usb-storage/START.html` (English)
- `media/usb-storage/START.de.html` (German)

The exported FAT image lives at `/var/storage0.img`; the backing store is
prepared by `etc/init.d/retrode3-storage-gadget@storage0`.

## Why image replacement was changed

Older package updates ran `rm -f /var/storage0.img` even while the
USB Mass Storage function exported it. The revised `prepare` action
builds a fresh FAT image as a sibling of the old file, mounts it locally,
copies the tracked source pages, unmounts it, then atomically renames it to
`/var/storage0.img`. This does not unbind the USB gadget.

A host that already mounted the old image continues to see the old bytes;
it receives the new contents after a safe USB reattachment or reboot.
Do not force-refresh the LUN while the host is accessing it.

## Test on hardware (not yet completed for this change)

1. Install the new pages to `/media/usb-storage/` and the updated init
   script to `/etc/init.d/retrode3-storage-gadget@storage0`.
2. Run `sh -n /etc/init.d/retrode3-storage-gadget@storage0`.
3. Preserve the original backing image while testing:
   `cp -p /var/storage0.img /root/storage0-before-docs.img`.
4. Run `service retrode3-storage-gadget@storage0 prepare`.
   Verify that it completes and that SSH, NCM and the mounted storage
   device remain connected. The host will still see the previous image.
5. Reboot normally and reopen both START pages from the exported USB disk.
   Check both links, mDNS/numeric fallback, network and storage behavior.
6. Build and install the revised `retrode3-storage-gadget` .deb via the
   existing `mySTEP.make`/`make-all` pipeline, then test a package
   upgrade while the host is connected. It should prepare a new image
   without dropping the USB connection.

**Limitations:** This change has not been validated on Windows or macOS.
The docs reflect standard CDC-NCM host support, and mark the optional
internet-sharing path as a separate setup not yet tested for this device.
