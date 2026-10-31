# Security policy

## Reporting a vulnerability

Please don't report security problems in a public issue. Use GitHub's [private vulnerability reporting](https://github.com/n0rthstar88/peripheralhub/security/advisories/new) instead, with steps to reproduce and the version or commit you tested.

This is a volunteer project, so replies are best-effort and there is no guaranteed response time.

## Supported versions

Only the latest code on `main` gets fixes.

## What's in scope

These are the parts most worth a look:

- The udev rule (`data/70-peripheralhub.rules`), which gives the logged-in user access to the supported keyboard and mouse.
- The installer's root step (`install.sh --udev-only`), run through sudo or pkexec.
- Handling of files the app reads and rewrites, such as `~/.config/hypr/monitors.lua`, settings and keyboard backups.
- Macro contents. Macros are stored on the keyboard and in its backups **unencrypted**, so don't put passwords in them.
