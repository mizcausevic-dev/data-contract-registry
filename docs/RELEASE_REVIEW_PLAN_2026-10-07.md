# Data contract registry release review (2026-10-07)

## Goal

Make the registry's compatibility decisions, in-memory history, Decision Card owner bridge, and package publication path reliable enough for a public reference release.

## Current state

Observed at `main` commit `22211b6008e94d99fcd3ada4dec759cc40d69373`: v0.1.1, in-memory `ContractRegistry`, unauthenticated loopback FastAPI app, optional best-effort audit sink, PyPI OIDC tag workflow. Baseline Python 3.11 suite: 65 passed; Ruff check/format and mypy passed. No persistent store, approval workflow, tenant authorization, or deployment target is present.

## Scope

- Correct direction-specific compatibility gaps and version-history consistency.
- Prevent caller mutation of registered contract history.
- Validate contract invariants that CSV and SQL consumers depend on.
- Treat extracted Decision Card owners as unverified candidates, and avoid sensitive audit-error output.
- Add a serialized synthetic contract fixture and gate PyPI publication on tests, tag match, and distribution checks.

No hosted deployment, customer data, new credentials, new production dependency, tag, or PyPI upload is included in this branch.

## Acceptance criteria

- Regression tests prove changed compatibility directions, archive/dry-run parity, copy isolation, owner-bridge limitations, and error redaction.
- Python 3.11 tests, Ruff, mypy, package build, Twine, package inventory, and dependency/secret checks have recorded outcomes.
- Exported JSON fixture validates as `DataContract` and matches the YAML source.
- README, API description, and release metadata avoid implying buyer approval or customer-ready hosting.

## Risks and release class

R3 for a public API package. Compatibility behavior and stricter schema validation may reject previously accepted contracts; bump to v0.2.0. In-memory state remains process-local and unauthenticated, so only reference/loopback use is supported. Audit URL is operator-supplied, and audit delivery remains best-effort.

## Design and sequence

1. Add focused tests for observed failures.
2. Correct model, checker, registry, and bridge behavior; document semantics.
3. Add release workflow gates and check the exact wheel/sdist contents.
4. Run local checks, inspect diff, prepare PR. Root release coordinator decides on merge/tag/publication.

## Verification and rollback

Run `python -m pytest -q`, `ruff check src tests`, `ruff format --check src tests`, `mypy src`, `python -m build`, `twine check dist/*`, and distribution/fixture verification. PR CI covers Python 3.11/3.12/3.13 and CodeQL. Rollback before publication is to close the PR; after publication, restore from the previous source tag and publish a corrective version. Published PyPI versions cannot be overwritten.

## Progress and outcome

- [x] Clone and inspect live remote, repository instructions, baseline code, tests, and workflows.
- [x] Execute Python 3.11 baseline: 65 passed; Ruff and mypy passed.
- [x] Implement compatibility, history isolation, owner-candidate, audit redaction, and publication-gate fixes.
- [x] Execute Python 3.11 suite (102 passed, one upstream deprecation warning), Ruff, mypy, Actionlint, isolated build, Twine, distribution inventory, wheel import smoke, Gitleaks, and pip-audit.
- [ ] Record final commit, PR, CI, distribution inventory, and residual risks.

## Decisions

Keep the API process-local and reference-only. The owner bridge maps fields to candidate records; it does not verify approval, signatures, employment, or paging authority. No contract-derived FK/unique/check claims: the current `DataContract` model has no such declarations.

## Outcome

Local checks found no dependency advisories after upgrading only the ignored test environment's packaging tools. The package remains a reference implementation. GitHub Actions matrix, PyPI Trusted Publisher configuration, and hosted behavior require live verification after the branch is pushed. The audit sink is best-effort and no retention or durable state exists. A v0.2.0 release requires a merged main commit, matching tag, successful exact-head CI, and a live PyPI artifact check; this branch does not perform those actions.
