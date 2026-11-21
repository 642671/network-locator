# Project Layout

```text
network-locator/                       # proposed repository name
|- apps/
|  |- tos7/                           # TOS 7 iframe Deb application
|  |  |- backend/
|  |  |  |- network-locator-service
|  |  |  |- network_locator/
|  |  |  |  |- core.py
|  |  |  |  |- server.py
|  |  |  |  `- __init__.py
|  |  |  `- tests/
|  |  |- frontend/
|  |  |  |- index.html
|  |  |  |- styles.css
|  |  |  |- csv.js
|  |  |  `- app.js
|  |  |- images/icons/network-locator.svg
|  |  |- init.d/networklocator-system.service
|  |  |- DEBIAN/
|  |  |  |- control
|  |  |  |- postinst
|  |  |  |- prerm
|  |  |  `- postrm
|  |  |- tools/preview_server.py
|  |  |- config.ini
|  |  |- network-locator.env
|  |  |- network-locator.lang
|  |  |- build.py
|  |  |- VERSION
|  |  |- CHANGELOG.md
|  |  `- README.md
|  `- windows/                       # reserved, phase 5
|- shared/
|  `- web/                           # reserved, phase 4
|- packaging/                        # reserved, phase 2/3
|- tools/                            # reserved, phase 2
|- docs/
|  |- PROJECT_LAYOUT.md
|  |- IDENTITY_1.1.0.md
|  |- MIGRATION_PHASE1.md
|  |- REQUIREMENTS_SAVED_MACS.md
|  `- screenshots/
|- .github/workflows/tos7.yml
`- README.md
```

## Ownership boundaries

- `apps/tos7/backend/network_locator/core.py`: interface discovery, bounded
  probing, neighbor parsing, suffix matching, and scan state.
- `apps/tos7/backend/network_locator/server.py`: TOS proxy routing, JSON API,
  Unix socket.
- `apps/tos7/frontend/`: presentation and user interaction only.
- `apps/tos7/DEBIAN/`: installation and removal lifecycle.
- `apps/tos7/init.d/`: systemd unit copied into `/etc/systemd/system`. The
  directory name is kept as `init.d/` because the Deb contract and build
  script use it; it may be renamed in a later phase while the packaged path
  stays unchanged.
- `apps/tos7/build.py`: deterministic single-package Deb generation and
  verification for this app.
- `docs/`: repository documentation, not packaged.

## Packaged layout is fixed

Source paths may move, but the Deb must always contain:

```text
/usr/local/network-locator/config.ini
/usr/local/network-locator/network-locator.lang
/usr/local/network-locator/network-locator.env
/usr/local/network-locator/LICENSE
/usr/local/network-locator/bin/network-locator-service
/usr/local/network-locator/images/icons/network-locator.svg
/usr/local/network-locator/init.d/networklocator-system.service
/usr/local/network-locator/lib/network_locator/*.py
/usr/local/network-locator/webui.bz2
```

App id `network-locator`, systemd unit `networklocator-system`, socket
`/var/api/network-locator.sock`, and runtime user `network-locator` are also
fixed.
