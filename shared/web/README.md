# Shared web modules (reserved)

This directory will hold front-end modules used by both the TOS 7 and Windows
apps, loaded as plain `<script>` tags. No bundler or front-end runtime will be
introduced.

Phase 1 intentionally contained **no moved code** here, and phase 2 only
renamed the application identity. The extraction of `csv.js`, formatting,
storage, table, tooltip, and theme helpers happens in phase 4, after the
characterization tests exist.

Candidate first moves (from the refactor assessment):

- `csv.js` (already byte-identical between TOS and Windows)
- MAC/IP formatting and IPv4-aware sorting
- filter/sort predicates
- storage keys and cache signatures
- retry-delay calculation

Each extraction must keep `?v=__APP_VERSION__` cache busting and update the
`webui.bz2` required-file checks in `apps/tos7/build.py`.
