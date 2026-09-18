# Contributing

Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `build:`,
`ci:`, `refactor:`, or `chore:`) with an optional scope. Pull-request titles are
validated because squash merges use that title.

Maintain `CHANGELOG.md` under `Unreleased` for user-visible behavior, security
changes, migrations, operational changes, and deprecations. Test-only and
internal refactors do not need an entry unless they change an operator-facing
contract. Releases move entries into a dated semantic-version section; breaking
changes include a migration note.

Never commit `.env` files or credentials. Examples contain variable names only.
Follow red-green-refactor: add a focused failing test, record the failure, add
the smallest implementation, then run the focused and full relevant suites.
