# Migration Notes — Phase 0 / Phase 1

> Historical record. Phase 1 deliberately preserved the old
> `lan-mac-finder` identity. Phase 2 superseded that identity with
> `network-locator` / version `1.1.0`; see `docs/IDENTITY_1.1.0.md`.
> The hashes below describe the `v1.0.017` baseline and remain valid as the
> rollback reference.

Date: 2026-11-21

## Baseline (phase 0)

Source repository: `642671/lan-mac-finder-tos7`, branch `main`,
commit `eb4d3285a5c33fd1c1f6786e76ac468024c62353` (tag `v1.0.017`),
working tree clean.

Build environment: WSL2 Debian, Python 3.12.3, zlib 1.3 (runtime 1.3),
`dpkg-deb` 1.22.6, x86_64.

Rebuilt at the tag:

| Package | Size | SHA256 |
| --- | ---: | --- |
| `lan-mac-finder_1.0.017_x86_64.deb` | 53080 | `407596e90e173b9db10b45d674e7652de0dc2f02f3fcec7467528c3e06abf59a` |
| `lan-mac-finder_1.0.017_aarch64.deb` | 53082 | `ce12ad5d68fb1c1c883a84dcfc73d3ac2ff3c323fc6bd59ac5fa19b7f1477c8e` |

Two consecutive builds in the same environment produced byte-identical
archives for both architectures.

Tests at the tag: 50 backend `unittest` tests pass; `node --check` passes for
`frontend/csv.js` and `frontend/app.js`; 19 Node tests pass.

Caveat: the `dist/` artifacts already present in the source repository carry
different SHA256 values (`dec87594…` / `25491939…`, 53210 bytes each) because
they were compressed with a different zlib/bz2 build. Their **unpacked file
contents are identical** to the rebuild. Byte equality is only meaningful
within one Python/zlib environment, which is why the phase 1 gate compares
builds made in the same environment.

Full baseline evidence lives outside this repository, in
`dev-test/baseline/` (not committed).

## Phase 1 (this tree)

- TOS source copied from the `v1.0.017` tree into `apps/tos7/`.
- No application file was modified. `build.py` is byte-identical to the
  original; `ROOT = Path(__file__).resolve().parent` now resolves to
  `apps/tos7`, and every packaging input lives below it.
- App id, package name, systemd unit name, socket path, runtime user,
  `/usr/local/lan-mac-finder/` package paths, dependencies, and version are
  unchanged.
- `.github/workflows/build.yml` became `.github/workflows/tos7.yml` with only
  `working-directory: apps/tos7` and artifact paths adapted.
- `docs/PROJECT_LAYOUT.md` and `docs/screenshots/` moved to the repository
  root; they are not packaged.
- `apps/tos7/tools/preview_server.py` stayed in place because the package
  contract test asserts that path and it resolves the frontend via
  `parents[1]`.
- `apps/tos7/VERSION` remains the authoritative version during phase 1. A
  root-level version source is deferred to phase 2 to avoid two competing
  sources.
- `shared/web/`, `packaging/`, and root `tools/` contain placeholders only.

### Acceptance result

| Check | Result |
| --- | --- |
| x86_64 Deb SHA256 vs baseline | identical |
| aarch64 Deb SHA256 vs baseline | identical |
| `dpkg-deb --info` output | identical |
| `dpkg-deb --contents` output | identical |
| Unpacked file SHA256 list | identical |
| Backend tests in new layout | 50/50 pass |
| Frontend tests in new layout | 19/19 pass |

No repository was created, and no commit, tag, or push was made. The original
`642671/lan-mac-finder-tos7` checkout and the Windows `lan-mac-finder-exe`
checkout remain clean at their tags and are the rollback points.
