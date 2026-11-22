# 网络定位 (Network Locator)

Unified source tree for the 网络定位 (Network Locator) family. This repository was
migrated from the standalone TOS 7 repository
[`642671/lan-mac-finder-tos7`](https://github.com/642671/lan-mac-finder-tos7),
which remains the published and rollback baseline until the migration is
accepted.

## Status

- **Phase 1 (done): source move only.** TOS source now lives in `apps/tos7/`;
  its `v1.0.017` builds were byte-identical to the original repository.
- **Phase 2 (done): new application identity.** The TOS app was renamed to
  `network-locator` (display name "网络定位") with version `1.1.0`.
  The app id, package name, systemd unit, socket, runtime user, and
  `/usr/local/network-locator/` package paths all use the new identity, so
  TOS and App Center treat it as a **new application** rather than an update
  of `lan-mac-finder`. Feature behavior is unchanged from `1.0.017`.
- **Phase 3 (current): 我的设备 section.** Version `1.2.0` adds a saved MAC
  section that stores up to 8 MAC suffixes with notes, resolves each entry's
  current IP after every scan, copies an IP with one click, and keeps the
  existing generic MAC search unchanged. Version `1.2.1` separates
  「我的设备」 and 「设备总表」 into two sections, puts the 「设备总表」 heading
  directly above its device list, applies a green visual refresh, simplifies
  the device table with row selection and inline copy, adds network chips,
  fixes horizontal tooltips, shows an inline loading row while refreshing,
  and updates the app icon.
- **Published.** The repository is public at
  `https://github.com/642671/network-locator`; releases `v1.1.0-r2` and
  `v1.2.0`, `v1.3.0` and `v1.3.1` carry the x86_64 and aarch64 Debs and SHA256 sidecars.
  `v1.3.2` is the current build under test.
- **TDP:** App `network-locator` is registered (platform `x86_64`) and version
  `1.1.0` was submitted on 2026-11-21. It is currently in platform review
  (`status=0`). `1.2.x` will be submitted after that review ends.
- The `aarch64` Deb is available in the Release but cannot be submitted under
  the same TDP App because an App is bound to one architecture and an App ID
  can only be registered once. A separate identity would be needed for an
  ARM listing; this is pending an owner decision.
- The Windows portable build (`642671/lan-mac-finder-exe`) has **not** been
  migrated.

## Identity

| Item | Value |
| --- | --- |
| App id / package | `network-locator` |
| Display name | 网络定位（Network Locator） |
| systemd unit | `networklocator-system.service` |
| Socket | `/var/api/network-locator.sock` |
| Runtime user | `network-locator` |
| Package root | `/usr/local/network-locator/` |
| Version | `1.3.2` |

The old `lan-mac-finder` package is not upgraded by this build; installing it
alongside is possible only because every path, user, socket, and unit name
differs. A real NAS should not run both at the same time.

## Layout

| Path | Purpose |
| --- | --- |
| `apps/tos7/` | TOS 7 iframe Deb application, the only store candidate |
| `apps/windows/` | Reserved for the Windows portable build (phase 5) |
| `shared/web/` | Reserved for front-end modules shared by both apps (phase 4) |
| `packaging/` | Reserved for the extracted deterministic Deb builder (phase 2/3) |
| `tools/` | Reserved for repository-level tooling (version sync, preflight) |
| `docs/` | Project layout, migration notes, screenshots |

## Build and test (TOS 7)

```bash
cd apps/tos7
python3 -m unittest discover -s backend/tests -v
node --check frontend/csv.js && node --check frontend/app.js
node --test tests/frontend_csv.test.js tests/frontend_search_state.test.js
python3 build.py --platform x86_64
python3 build.py --platform aarch64
```

Requirements: Python 3.10+, Node 20 (tests only). No third-party runtime
dependencies and no front-end build chain.

The local preview server runs from `apps/tos7` and serves synthetic data:

```bash
python3 apps/tos7/tools/preview_server.py --port 4178
```

## Version source

`apps/tos7/VERSION` remains the authoritative version, together with the other
locations listed in `apps/tos7/README.md`. A single root-level version source
and `tools/sync_version.py` are still pending; do not add a competing version
file before then.

## License

See `LICENSE`.
