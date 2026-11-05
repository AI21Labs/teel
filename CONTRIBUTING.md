# Contributing to Teel

Thanks for your interest. Issues and pull requests are welcome.

## Setup

Teel requires exactly Python 3.12.13, because the `frameinspect` C extension builds against CPython's internal headers.

```
git clone https://github.com/<your-user>/teel.git
cd teel
uv sync
```

## Tests

Run the suite before opening a pull request; CI runs the same command:

```
uv run python -m unittest discover -s tests -v
```

New behavior should come with a test in `tests/`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Keep each pull request to one logical change.
3. Use a [Conventional Commits](https://www.conventionalcommits.org/) title, such as `feat: support generators` or `fix: handle empty input`. Releases are versioned from these titles: `feat` bumps the minor version and `fix` bumps the patch version.
4. A code owner reviews every pull request. It merges once CI passes and all review conversations are resolved.

For larger changes, open an issue first so we can agree on the approach.
