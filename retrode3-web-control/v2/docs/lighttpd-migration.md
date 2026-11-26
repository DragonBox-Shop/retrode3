# PHP-free web control experiment (Bookworm)

This feature branch is deliberately **not** a package or image release.
The default PHP entrypoint, existing SysV unit, APT dependencies and
production image verification remain unchanged until the new gateway
passes its tests. Do not run the two cartridge backends concurrently.

## Implemented

- Static index.html (same UI), dual-mode JavaScript for old PHP and direct API.
- New loopback-only http_gateway.py reuses the existing service.Handler,
  MANAGER, AUTO and CLI interface. No cartridge logic is duplicated.
- Optional Basic authentication against the existing PHP bcrypt file,
  fail-closed when the file is unreadable. New Python password helper
  writes bcrypt for rollback compatibility. Bookworm Python 3.11 and
  libcrypt are required; Python crypt is deprecated and removed in 3.13.
- Signed CSRF cookie (HttpOnly, SameSite=Strict), token returned by a
  no-store session endpoint, origin and Host checks, no PHP sessions.
  Currently HTTP only; no claim of transport encryption.
- ROM uploads use raw application/octet-stream with a 4 MiB cap and
  a 64 KiB read chunk. A hidden temporary file is linked atomically to
  a unique non-overwriting name after complete transfer. Directory FDs
  and O_NOFOLLOW reject symlinked root/system folders.
- Bounded request concurrency and socket timeouts.
- Standalone Lighttpd test config on loopback port 8080 (use SSH
  forwarding); only the API/index are proxied and static assets served.
  This is not yet the final public port 80 configuration.

## Hardware-independent checks before deployment

Use a Debian 12 environment (Python 3.11, Node.js, Lighttpd installed).
From the OS repository root:

```sh
python3 -m unittest discover -s retrode3-web-control/v2/tests -p 'test_http_gateway.py' -v
node --check retrode3-web-control/v2/web/assets/app.js
node retrode3-web-control/v2/tests/test_frontend_flash_writer.js
```

Then run the full existing preflight with its tools installed.
For the Lighttpd configuration check, create a separate lab document
root containing only index.html, assets/ and locales/ (never PHP files),
and run lighttpd -tt -f retrode3-web-control/v2/service/lighttpd-test.conf.
Use a fake ROM directory and mocked cartridge backend for proxy HTTP
smoke tests before switching any service on the real device.

## Remaining work before a package candidate

- Run unit tests and real Lighttpd proxy smoke tests, including full
  4 MiB streaming upload, download and original Host/cookie forwarding.
- Review request framing, cross-origin and session handling, bcrypt
  compatibility and password changes; retain optional password and
  protect future developer settings with explicit authentication.
- Test all read/write/probe/status flows, multiple clients, interrupted
  uploads and file permissions, preferably on a spare SD with the
  reference kernel first. Never start two AUTO managers.
- Update Debian package dependencies, webroot, SysV startup, image
  verification and rollback/upgrade migration. Keep existing credentials,
  ROMs and core activation. Apache/PHP must not be removed until a
  working replacement is installed and verified. Avoid broad autoremove.
- Compare PSS/SwapPSS and latency with Apache/PHP on the same kernel.
- No changes to the master/stable or regular release tag pipeline.
