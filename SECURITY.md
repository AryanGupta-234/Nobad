# Security policy

This policy covers both NOBAD products in this repository: **NOBAD VPN** (`apps/vpn/`) and **NOBAD File Bridge**
(`apps/file-bridge/`). NOBAD VPN runs with administrator rights and changes firewall rules. NOBAD File Bridge holds server
credentials and runs commands on remote servers. Security reports are taken seriously for both.

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository
(<https://github.com/nobad-studio/nobad/security/advisories/new>).

Include what you found, how to reproduce it, which product it affects, and the version: for NOBAD VPN the version
from *Settings → Help* and your Windows version; for NOBAD File Bridge the commit you tested and your operating system.
You'll get an answer as soon as possible. NOBAD is a small independent project, so please allow a little time.
Fixes are released as a new version, and reporters are credited unless they prefer otherwise.

## Supported versions

### NOBAD VPN

| Version | Supported |
|---|---|
| 1.5.x (latest) | yes |
| 1.4.x | security fixes only until 2026-12-31 |
| older | no (please update) |

### NOBAD File Bridge

Not released yet. Reports against the current code on `main` are welcome; report them privately the same way.

## Scope

For NOBAD VPN, these are especially interesting:
- the elevated parts: the no-UAC launcher task, the boot guard, the firewall rules, and the tunnel services;
- the local API (`127.0.0.1`, token and origin checks);
- the updater's signature checks;
- handling of WireGuard configs and private keys;
- the reset and repair paths.

For NOBAD File Bridge, these are especially interesting:
- the encrypted credential vault and how secrets are stored, logged or exported;
- SSH/SFTP and FTP/FTPS handling, including host key and TLS checks and file names or output from a server;
- deployment commands run on remote servers.

These are out of scope:
- the WireGuard protocol and WireGuard for Windows itself (report those to WireGuard);
- the security of VPN providers' servers.
