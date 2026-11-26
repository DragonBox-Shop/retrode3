# USB networking and optional developer SSH (development)

USB NCM uses a single link supervisor. After carrier appears, a host DHCP
server has up to 12 seconds to supply a lease. If there is no valid offer,
the DHCP client is stopped and the device serves its original 172.31.255.1/29
network. Reconnecting the cable repeats the decision. Do not activate host
Internet sharing while the device is already serving DHCP; reconnect first.
A host-provided default route is installed with metric 500; DNS is handed to
resolvconf, and avahi advertises retrode3.local. Test hostname resolution on
Windows, Linux and macOS, including multiple devices with the same name.
No claim of validated cross-platform behavior yet.

SSH defaults off and is separate from USB serial and the welcome disk.
For development, set the optional web password via the trusted root console:

    retrode3-web-v2-auth enable

Then enter General Settings, Developer settings, confirm the web password
and set a separate root SSH password. This also changes the root console
password. The password is not passed in argv or logged. HTTP is not encrypted;
only use the local USB link or a trusted network. SSH listens on all interfaces
when explicitly enabled; forwarding is disabled. Disable stops new sessions;
existing sessions may remain active until they disconnect. The web-password
management helper disables SSH when removing web authentication. No key is
embedded in an image. Existing locally installed keys are not removed.
SFTP support uses Debian's openssh-sftp-server without openssh-server.
A secure first-time web password setup and the full hardware test are pending.
