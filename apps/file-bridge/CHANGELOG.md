# NOBAD File Bridge changelog

## Unreleased

* New interface: Server health and Services.
  * Server health shows CPU, memory, network, disks, the biggest folders and the busiest processes, with a small
    chart for the last minute. It reads the server only while you look at it.
  * Services lists systemd services with failed ones first. You can start, stop, restart and reload them, choose
    whether they start at boot, read their logs, and install a new one.
* Fixed (classic window too): starting, stopping or restarting a service, reloading systemd, installing a unit file
  and stopping a process no longer report success when the command failed. You now see the server's reason. When
  sudo needs a password, it says so at once instead of waiting forever.
* New interface: Deployments.
  * Every deploy starts with a preview, with an optional build on your computer first.
  * Deploying makes a backup, uploads, runs your commands and checks that the site works. If any step fails, the
    site goes back to how it was by itself.
  * A pipeline shows each step as it happens.
  * History keeps every run with its steps and output.
  * Earlier backups and releases can be restored.
  * A lock left behind by a crashed run is only removed if you say so.
* New interface: Sync folders. Every sync starts with a preview of what would be copied, replaced or deleted, and
  nothing changes until you press Sync now. Replacing or deleting files asks first. Two-way jobs remember the
  last sync, so changes and deletions on either side cross over. Files changed on both sides wait for your choice:
  keep yours, keep the server's, keep both or skip, with a side-by-side compare. If files change between the
  preview and the sync, nothing runs and you get a fresh preview.
* New interface: the Credential vault. Secrets stay hidden until you reveal or copy one; revealed values hide again
  after 30 seconds and a copied secret is cleared from the clipboard after 30 seconds. The vault locks itself after
  10 minutes without use (change it in Settings), slows down repeated wrong master passwords, and includes a
  strong password generator. The classic window reads the same vault.
* Security: the code editor no longer loads Monaco from cdnjs or unpkg. It ships with the app, in the classic window
  and in the new interface, so editing works offline and no outside code runs next to the app (#30).
* New interface: an Editor for server and local files. Saving checks that nobody changed the file since you opened
  it; if they did, you can compare both versions side by side, overwrite with yours or take theirs. Unsaved
  changes are marked, kept across screen changes, and survive a disconnect.
* New interface: Terminal tabs for the connected server and for this computer, next to your files. They keep
  running when you switch screens, keep what they showed if the window reloads, and close with the server's
  connection. "Open terminal here" from the Files context menu. Copy and paste with Ctrl+Shift+C / Ctrl+Shift+V.
* New interface (`python -m app.web`): Connections and Files. Save servers, connect with a password, SSH key or
  agent (paste an `ssh` command to fill the form), and check an unknown server's fingerprint before trusting it.
  Files shows this computer and the server side by side, stays quick in folders with thousands of files, and
  works from the keyboard (F5 copy, F2 rename, F7 new folder, Delete). Uploads and downloads show live progress in
  the dock; if something already exists you choose once: keep both, skip or replace.
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
