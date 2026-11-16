# NOBAD File Bridge changelog

## Unreleased

* Security: a server can no longer make a download write outside the folder you chose. Names such as `../x`,
  `..\x`, `a/b` or `/etc/x` in a listing are hidden (with a warning) and refused by folder downloads (#29).
* Fixed: deleting a folder on an SFTP server no longer follows symlinks inside it, and deleting a symlink to a
  folder removes only the link. Folder downloads no longer follow symlinked folders.
* Security: playbooks only type the sudo password into sudo's own prompt, once. Output from the server that merely
  looks like a sudo prompt no longer receives it, and an echoed password is masked in the output (#32).
* Playbooks that use sudo now ask for the sudo password before they run. Reusing your SSH login password is an
  option you tick, not the default.
* Fixed: running a playbook from the Playbooks page failed with an internal error.

## 0.4.0

* First version in the NOBAD repository (imported from the standalone Remote File Manager project, renamed to NOBAD File Bridge).
* SSH/SFTP and FTP/FTPS browsing, queued transfers, cross-server relay, baseline-aware two-way sync, remote
  editing, embedded terminals, a master-password encrypted credential vault, and deployments with health checks
  and rollback.
