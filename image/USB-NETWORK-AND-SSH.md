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

SSH defaults off, independently of USB serial and the welcome disk.
In General Settings / Advanced settings, first set the shared root/developer
password using the directly connected USB network. Existing usable root
passwords are recognized; locked existing hashes are never replaced by
first-time setup. No separate developer password database: /etc/shadow is
the only source of truth. All subsequent changes require the current root
password. Enabling SSH does not change the password; disabling SSH does not
lock the root account. The ordinary optional web password is independent.
Use passwd root locally for recovery. No key or default password is embedded.
HTTP transmits credentials unencrypted; use only a trusted USB connection
or network. SSH listens on all interfaces when explicitly enabled, forwarding
disabled. Existing sessions may remain active after disabling SSH.
SFTP support uses Debian's openssh-sftp-server without openssh-server.
Validate first setup, proxy trust boundary, password changes and SSH on hardware
before release. This is a development implementation.
