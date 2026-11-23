# Changelog

All notable changes to this repository are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Offline stored-run check. `make check` recomputes the weighted scores in
  `my_first_review/` with `calculate_recommendation` and fails if the README
  drifts. The formula match is not a validity result: reviews that omit a
  criterion match only when that criterion contributes zero. The previous
  "3 consolidated CSVs" count and the "$0.22 per paper" rate are withdrawn.
- `package.json` is marked private and its license field follows `LICENSE`.
  It is still an npm scaffold, not a release of the review tool.

- Governance baseline: LICENSE, security policy, code of conduct, contributor and
  support guides, issue and pull-request templates, CODEOWNERS, dependabot, and
  `.editorconfig` added. No research content changed.
