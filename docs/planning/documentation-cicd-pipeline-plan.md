# Unicorn Viz Documentation CI/CD Pipeline Plan

Owner: Studio Documentation
Status: draft
Last updated: 2026-05-24

## Purpose

Define the documentation quality pipeline that will be added to release engineering,
without implementing checks yet.

## Scope

This plan covers documentation validation for:

- core documentation under `docs/`
- root entry docs (`README.md`)
- complex drop-in docs under `drop-ins/*/docs/`

## Goals

1. Prevent broken internal links from shipping.
2. Enforce minimal doc metadata standards.
3. Detect stale docs before release cuts.
4. Keep docs synchronized with moved/renamed files.
5. Integrate documentation quality gates into the broader release pipeline.

## Proposed Pipeline Stages

### Stage 1: Fast PR Validation

Run on pull requests touching docs or markdown files:

- Link check (internal links and anchors)
- Metadata header presence check (`Owner`, `Status`, `Last updated`)
- Forbidden location check (planning/audit/debug docs at repo root)
- Optional markdown lint profile (light rules only)

Target runtime: under 2 minutes.

### Stage 2: Branch/Nightly Validation

Run on main branch and nightly schedule:

- Full repository link crawl
- Stale-doc report (age-based)
- Cross-reference integrity check for index pages (`docs/README.md`, `docs/drop-ins.md`)
- Report orphan docs not reachable from canonical indexes

### Stage 3: Release Gate Validation

Run on release tags and release candidate branches:

- Re-run full validation suite
- Fail release if critical documentation checks fail
- Attach docs validation report artifact to release workflow

## Check Definitions

## 1. Internal Link Integrity

- Validate relative links in markdown across docs and drop-in docs.
- Treat broken links as blocking in release gate.

## 2. Metadata Header Compliance

Required fields for maintained docs:

- `Owner`
- `Status`
- `Last updated`

Initial rollout policy:

- PR warning-only for first phase
- release-gate enforcement after baseline cleanup complete

## 3. Location Policy Enforcement

- Root markdown limited to top-level entry docs.
- Planning/debug/audit files must live in `docs/planning`, `docs/debug`, `docs/audits`, or `docs/archive`.

## 4. Canonical Index Coverage

- New/moved docs must be linked from at least one index page.
- Complex drop-in docs should remain discoverable from `docs/drop-ins.md`.

## 5. Stale Documentation Report

- Generate report of docs with old `Last updated` values.
- Mark as advisory initially, then consider threshold-based enforcement.

## Integration with Release Engineering

This documentation pipeline should be wired into the future explicit CI/CD
release architecture tracked in `plan.md` Phase 6.

Expected alignment points:

- PR checks for contributor feedback loop
- Nightly health checks for maintenance drift
- Release gates for production confidence

## Rollout Strategy

1. Add workflow skeletons in non-blocking mode.
2. Baseline existing docs against metadata/location rules.
3. Turn on blocking behavior for link checks.
4. Gradually enforce metadata/index coverage once noise is reduced.

## Ownership and Maintenance

- Primary owner: Studio Documentation role.
- Secondary owners: subsystem/drop-in maintainers for their docs surfaces.
- Update this plan when pipeline behavior or thresholds change.

## Related Docs

- ../README.md
- installers.md
- ../../plan.md
