# Application identity 1.1.0

Date: 2026-11-21

## Decision

The TOS 7 application gets a **new application identity** rather than an
upgrade of the existing listing:

| Item | Old (`1.0.017`) | New (`1.1.0`) |
| --- | --- | --- |
| App id | `lan-mac-finder` | `network-locator` |
| Deb package | `lan-mac-finder` | `network-locator` |
| Display name | LAN MAC Finder | 网络定位（Network Locator） |
| systemd unit | `lanmacfinder-system.service` | `networklocator-system.service` |
| Socket | `/var/api/lan-mac-finder.sock` | `/var/api/network-locator.sock` |
| Runtime user | `lan-mac-finder` | `network-locator` |
| Package root | `/usr/local/lan-mac-finder/` | `/usr/local/network-locator/` |
| Python package | `lan_mac_finder` | `network_locator` |
| Service entry | `lan-mac-finder-service` | `network-locator-service` |
| Env / lang files | `lan-mac-finder.*` | `network-locator.*` |
| Icon | `lan-mac-finder.svg` | `network-locator.svg` |
| Version | `1.0.017` | `1.1.0` |

Every identifier that could collide with an installed `lan-mac-finder`
instance was changed: paths, user, socket, unit name, and front-end
`localStorage` keys (`lanMacFinder.*` → `networkLocator.*`). The old package
and new package can therefore coexist on disk, but only one should run at a
time because they would scan the same network and bind different sockets.

## What did not change

- Discovery, probing, MAC matching, scan state machine, API shape, and UI
  behavior are unchanged from `1.0.017`.
- Runtime dependencies: `python3 (>= 3.10)`, `iproute2`, `iputils-ping`,
  `systemd`. No third-party Python packages, no front-end build chain.
- Package format: single Deb per architecture, `config.ini`, `.lang`, icon,
  `webui.bz2`, lifecycle scripts, deterministic assembly.
- TOS safety rules: non-root user, `/var/api` untouched except the app socket,
  no `PrivateTmp`, `TimeoutStopSec=10`, `reset-failed` in `postinst`.

## Files changed for the rename

- `apps/tos7/config.ini`, `DEBIAN/control`, lifecycle scripts, systemd unit,
  `.env`, `.lang`, icon filename and `aria-label`.
- `apps/tos7/backend/network_locator/` (package directory), service entry,
  class names, `APP_ID`, docstrings.
- `apps/tos7/frontend/app.js`: app id, proxy-prefix candidates, storage keys,
  CSV filename; `frontend/index.html`: title and in-page product name.
- `apps/tos7/build.py` and `tools/preview_server.py`: app/system ids, packaged
  library path.
- `apps/tos7/backend/tests/` and `apps/tos7/tests/`: expected ids, paths,
  unit name, storage keys.
- `README.md`, `docs/PROJECT_LAYOUT.md`, the 14 language names and release
  notes, CI artifact names and release title.

The old repository `642671/lan-mac-finder-tos7` at tag `v1.0.017` is untouched
and remains the rollback point.

## Verification

Build environment: WSL2 Debian, Python 3.12.3, zlib 1.3, `dpkg-deb` 1.22.6.

| Package | Size | SHA256 |
| --- | ---: | --- |
| `network-locator_1.1.0_x86_64.deb` | 52524 | `7d1fe4e220bdc4ea7d89a80e25f36a40cb66cb6aa4c84af8546bdaa7909192a7` |
| `network-locator_1.1.0_aarch64.deb` | 52524 | `5eaab9f5d04f5beb19102c0a9f9234c4948282ffcd7fb5239262d6d1bcd12c22` |

- A second build in the same environment produced byte-identical archives.
- `dpkg-deb --info`: `Package: network-locator`, `Version: 1.1.0`, correct
  architecture, unchanged dependencies.
- `dpkg-deb --contents`: all payload files under
  `/usr/local/network-locator/`; service entry and lifecycle scripts are
  executable; unit, env, lang, icon, `webui.bz2`, and
  `lib/network_locator/*.py` are present.
- Packaged `config.ini`: `id`, `package`, `user`, `system_id`, `path`,
  `icon`, and `version` all use the new identity.
- Extracted payload and `webui.bz2` contain **no** `lan-mac-finder`,
  `lanmacfinder`, `lan_mac_finder`, `LanMacFinder`, or `LAN MAC Finder`
  strings.
- Backend tests: 50/50. Frontend syntax check and Node tests: 19/19.
- Runtime: `/health` over the Unix socket reports
  `app=network-locator`, `version=1.1.0`; the `/v2/proxy/network-locator/`
  prefix resolves; preview server reports `1.1.0-preview`.

Evidence: `dev-test/baseline/06-network-locator-1.1.0/`.

## Pending owner confirmation

1. Confirm `network-locator` is unused on the TerraMaster developer platform
   before registration (requires an authorized read-only `GET /v1/apps`).
2. Confirm the repository will be `642671/network-locator`; `config.ini`
   `official`/`help` already point there but the repository does not exist yet.
3. Real-NAS acceptance: fresh install, service/socket check, UI open, stop and
   re-enable, uninstall, and confirmation that an installed `lan-mac-finder`
   is not affected.
