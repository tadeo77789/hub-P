# Contributing

> Read this before your first commit. Same rules apply to `hub` and `pc-agent`.

## Language

Everything in the repository is written in English: code, identifiers, comments, docstrings, docs, commit messages, branch names and pull requests.
The only exception is user-facing text that Paula shows or speaks (chat bubbles, clouds, voice replies), which is in Spanish.

## Branch strategy

```
main          ← Production. Merge from develop (release) or hotfix only. Always stable.
  └── develop ← Integration. Merge from feature branches.
        ├── feat/<description>    ← One branch per feature
        ├── fix/<description>     ← One branch per bug fix
        ├── chore/<description>   ← Tooling, dependencies, docs, config
        └── hotfix/<description>  ← Urgent fix branched from main
```

Rules:
- Nobody commits directly to `main` or `develop`.
- One task = one branch = one pull request. Do not mix unrelated changes.
- Branch names are kebab-case: `feat/wake-word-detection`, `fix/hotkey-timeout`, `chore/add-ruff`.
- Delete the branch after merge.

## Commits (Conventional Commits)

```
<type>(<scope>): <lowercase imperative description, no trailing period>

<optional body: why, not what>
```

| Type | When |
|---|---|
| `feat` | New functionality |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no logic change |
| `refactor` | Code change without behavior change |
| `test` | Add or change tests |
| `chore` | Tooling, dependencies, CI |
| `perf` | Performance improvement |

- Keep the subject short (about 50 characters).
- Small commits, one topic each.
- No `Co-Authored-By` lines or tool attribution.

Examples:

```
feat(activation): detect wake word with strict threshold
fix(ui): reset robot to sleeping after error
chore(deps): add faster-whisper
```

## Pull requests

- Target `develop` (a `hotfix/*` targets `main`).
- Fill in `.github/pull_request_template.md`.
- At most about 400 changed lines, tests excluded. Split larger work.
- Merge strategy: **squash and merge** into `develop`; **merge commit** for `develop` → `main` releases. No rebase-and-merge.

## Versioning

[SemVer](https://semver.org/) `MAJOR.MINOR.PATCH`, independent per repository. The version lives in `pyproject.toml`.

- Bump the version in a PR to `develop` before releasing.
- After the release merge, tag the commit on `main` (`git tag -a v0.1.0 -m "Release v0.1.0"`) and create a GitHub Release with generated notes.

## Secrets

- API keys go in `.env` (git-ignored). `.env.example` lists the variable names with empty or dummy values, never real ones.
