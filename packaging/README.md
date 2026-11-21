# Packaging (reserved)

This directory will hold the deterministic Deb assembly extracted from
`apps/tos7/build.py` (phase 2/3), plus a local replica of the TerraMaster
package preflight checks.

Phase 1 kept `apps/tos7/build.py` unchanged so the produced Debs stayed
byte-identical to the published `v1.0.017` artifacts. Phase 2 only updated the
app-specific constants in `build.py` for the `network-locator` identity and
`1.1.0` version; the deterministic assembly itself is still unmodified and
has not been extracted yet.

Planned modules:

- `deb_builder.py`: ar/gzip/tar assembly, fixed mtime, gzip mtime=0, LF
  normalization, fixed ar headers. Must preserve current reproducibility.
- `tdp_contract.py`: TerraMaster package preflight (config.ini JSON fields,
  14 languages, icon rules including DOCTYPE/ENTITY rejection, required
  paths, size limits, SHA256).

The app-specific contract (app id, system id, language list, icon path) stays
with the app; only the mechanism is shared.
