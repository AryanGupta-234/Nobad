# NOBAD File Bridge changelog

## Unreleased

* Security: a server can no longer make a download write outside the folder you chose. Names such as `../x`,
  `..\x`, `a/b` or `/etc/x` in a listing are hidden (with a warning) and refused by folder downloads (#29).
* Fixed: deleting a folder on an SFTP server no longer follows symlinks inside it, and deleting a symlink to a
  folder removes only the link. Folder downloads no longer follow symlinked folders.
* Security: the data folder (`~/.remote-file-manager`) is now private on Linux and macOS: the folder is 0700 and
  the database, `known_hosts` and diagnostics log are 0600. Existing files are tightened on start, and a data
  folder that is a symlink or belongs to another user is refused (#31).
* If the data folder can't be used, the app no longer falls back to a shared `/tmp` folder. It uses a new private
  temporary folder for that session and says so in the log: saved connections and settings won't be kept.

## 0.4.0

* First version in the NOBAD repository (imported from the standalone Remote File Manager project, renamed to NOBAD File Bridge).
* SSH/SFTP and FTP/FTPS browsing, queued transfers, cross-server relay, baseline-aware two-way sync, remote
  editing, embedded terminals, a master-password encrypted credential vault, and deployments with health checks
  and rollback.
