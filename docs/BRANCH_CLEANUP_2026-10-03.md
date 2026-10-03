# GitHub branch consolidation — 2026-10-03

The user requested the approved dashboard on the default branch and only one
remaining GitHub branch (`main`). All four older branch tips were preserved as
archive tags before cleanup; their commits remain recoverable without retaining
extra branches. These tags are not deployment branches.

| Old branch | Archive tag | Original tip |
| --- | --- | --- |
| `arena/01a0240a-autonoc-project` | `archive/arena-01a0240a-2026-10-03` | `adeb6a45bf8b00383a8746734065a9521740e950` |
| `arena/01a04463-autonoc-project` | `archive/arena-01a04463-2026-10-03` | `c25785f842efe9e29a1a9f6eaa5a5282ea6fee9d` |
| `flyio-new-files` | `archive/flyio-new-files-2026-10-03` | `c357df5b257a5a3510499fe8ff1703adc91f03ed` |
| `flyio-scale-from-ui` | `archive/flyio-scale-from-ui-2026-10-03` | `8fd5d889ca62fdf3aa3d6931dbcb8f52932d0006` |

The first and last branches have commits not incorporated into the previous
`main`; archival preserves them without overwriting the user's approved app with
older deployment experiments. The old scaling PR is #2.

The current dashboard work originates on `arena/01a10260-autonoc-project` and is
to be merged through a pull request before its remote branch is removed. The
local Arena checkout stays on its assigned session branch.

## CI permission limitation

The application, tests, Docker configuration, documentation, local map fonts and
full proposed workflow are included in the repository. The exact updated
workflow is in `ci-proposed.yml`; GitHub rejected modification of the active
`.github/workflows/ci.yml` because the app connection lacks workflow-write
permission. The active file must be replaced separately using an authorized
connection or the GitHub web editor. No passwords or tokens are needed in chat.
