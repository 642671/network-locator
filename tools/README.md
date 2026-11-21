# Repository tools (reserved)

Planned repository-level tooling (later phases):

- `sync_version.py`: treat a single version source as authoritative and
  check/rewrite every version location:
  - TOS: `config.ini`, `DEBIAN/control`, `backend/network_locator/__init__.py`,
    `README.md`, `CHANGELOG.md`, 14 `release_note` prefixes in
    `network-locator.lang`, built `?v=` query parameters.
- `tdp_preflight.py`: run the TerraMaster package checks locally against both
  architecture Debs before a release.
- `preview_server.py`: move from `apps/tos7/tools/` once its root resolution
  is made repository-aware, and point it at `apps/tos7/frontend`.

The TOS app currently keeps `apps/tos7/tools/preview_server.py` in place,
because `apps/tos7/backend/tests/test_package_contract.py` asserts that
location and the script resolves its frontend via `parents[1]`.
