# Security policy

NOBAD VPN runs with administrator rights and changes firewall rules, so security reports are taken seriously.

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository
(<https://github.com/AryanGupta-234/Nobad/security/advisories/new>).

Include what you found, how to reproduce it, the NOBAD VPN version (*Settings → Help*) and your Windows version.
You'll get an answer as soon as possible. NOBAD is a small independent project, so please allow a little time.
Fixes are released as a new version, and reporters are credited unless they prefer otherwise.

## Supported versions

| Version | Supported |
|---|---|
| 1.3.x | yes |
| older | no (please update) |

## Scope

These are especially interesting:
- the elevated parts: the no-UAC launcher task, the boot guard, the firewall rules, and the tunnel services;
- the local API (`127.0.0.1`, token and origin checks);
- the updater's signature checks;
- handling of WireGuard configs and private keys;
- the reset and repair paths.

These are out of scope:
- the WireGuard protocol and WireGuard for Windows itself (report those to WireGuard);
- the security of VPN providers' servers.
