# Unicorn Viz Documentation Index

Owner: Studio Documentation
Status: active
Last updated: 2026-06-18

This is the canonical map for project documentation.

## Product Documentation

- [User Guide](user-guide.md)
- [Configuration Reference](configuration.md)
- [Effect Settings Reference](effect-settings.md)
- [Developer Guide](developer-guide.md)
- [Testing Guide](testing.md)
- [Drop-in Documentation Registry](drop-ins.md)
- [Security Policy](../SECURITY.md)
- [Marketing](marketing/README.md)

## Working Documentation

- Planning: [docs/planning](planning)
- Cross-platform installer plan (gold-star roadmap, refreshed 2026-06-21): [docs/planning/installers.md](planning/installers.md)
- Auto VJ training protocol: [docs/planning/auto-vj-training-pack-protocol.md](planning/auto-vj-training-pack-protocol.md)
- Hotkey architecture refactor: [docs/planning/hotkey-architecture-refactor.md](planning/hotkey-architecture-refactor.md)
- Hotkey cross-platform conflict remap plan (2026-06-03): [docs/planning/hotkey-cross-platform-conflict-remap-plan-2026-06-03.md](planning/hotkey-cross-platform-conflict-remap-plan-2026-06-03.md)
- Prioritized action plan (2026-06-03): [docs/planning/prioritized-action-plan-2026-06-03.md](planning/prioritized-action-plan-2026-06-03.md)
- Effect tweakables backlog (2026-06-04): [docs/planning/effect-tweakables-backlog-2026-06-04.md](planning/effect-tweakables-backlog-2026-06-04.md)
- Feature review remediation plan (2026-06-10): [docs/planning/feature-review-remediation-plan-2026-06-10.md](planning/feature-review-remediation-plan-2026-06-10.md)
- Multi-head viewport regression tests issue (2026-06-14): [docs/planning/multihead-viewport-regression-tests-issue-2026-06-14.md](planning/multihead-viewport-regression-tests-issue-2026-06-14.md)
- Help screen additions milestone (2026-06-14): [docs/planning/help-additions-milestone-2026-06-14.md](planning/help-additions-milestone-2026-06-14.md)
- Global atomic state unification (2026-06-18): [docs/planning/global-state-unification-2026-06-18.md](planning/global-state-unification-2026-06-18.md)
- Compositor dedup implementation plan (2026-06-18): [docs/planning/compositor-dedup-implementation-plan-2026-06-18.md](planning/compositor-dedup-implementation-plan-2026-06-18.md)
- Deferred work register (2026-06-18): [docs/planning/deferred-work-2026-06-18.md](planning/deferred-work-2026-06-18.md)
- Deferred offscreen audience FBO plan (2026-06-18): [docs/planning/offscreen-audience-fbo-deferred-plan-2026-06-18.md](planning/offscreen-audience-fbo-deferred-plan-2026-06-18.md)
- Mono-file refactor plan (2026-06-19): [docs/planning/mono-file-refactor-plan-2026-06-19.md](planning/mono-file-refactor-plan-2026-06-19.md)
- ProjectM-only mode + effects browser examination (2026-06-30): [docs/planning/projectm-only-mode-and-effects-browser-2026-06-30.md](planning/projectm-only-mode-and-effects-browser-2026-06-30.md)
- Effects consolidation analysis (Option B category packs selected 2026-06-30): [docs/planning/effects-consolidation-analysis.md](planning/effects-consolidation-analysis.md)
- Active audit tracker: [docs/audits](audits)
  - Feature review tracker (active): [docs/audits/feature-review.md](audits/feature-review.md)
  - Full system audit (2026-07-01): [docs/audits/2026-07-01-full-system-audit.md](audits/2026-07-01-full-system-audit.md)
  - Full system audit (2026-06-19): [docs/audits/2026-06-19-full-system-audit.md](audits/2026-06-19-full-system-audit.md)
  - Full system audit (2026-06-17): [docs/audits/2026-06-17-full-system-audit.md](audits/2026-06-17-full-system-audit.md)
- Archived debug and handoff notes: [docs/archive/debug](archive/debug)
  - Audio startup regression + validation hardening (2026-06-04): [docs/archive/debug/audio-startup-regression-2026-06-04.md](archive/debug/audio-startup-regression-2026-06-04.md)
- Archived audit reports and review snapshots: [docs/archive/audits](archive/audits)
  - Full system audit (2026-06-01): [docs/archive/audits/2026-06-01-system-audit.md](archive/audits/2026-06-01-system-audit.md)
  - Hotkey refactor P0 hotfix brief (2026-06-01): [docs/archive/audits/2026-06-01-hotkey-refactor-regressions.md](archive/audits/2026-06-01-hotkey-refactor-regressions.md)
  - 24-hour committed-work regression audit (2026-06-03): [docs/archive/audits/2026-06-03-24h-regression-audit.md](archive/audits/2026-06-03-24h-regression-audit.md)
- Historical/superseded notes: [docs/archive](archive)

## Documentation SOP

- Canonical user/developer docs live under `docs/`.
- Root markdown files are limited to top-level entry docs.
- New docs must be linked from at least one index page.
- Maintained docs should include `Owner`, `Status`, and `Last updated`.
- Superseded docs should be moved to `docs/archive/` and marked as historical.

## Maintenance Checklist

- Update docs when behavior or controls change.
- Verify links when moving files.
- Keep drop-in docs status current in [drop-ins.md](drop-ins.md).
- Keep planning work visible in [../plan.md](../plan.md).
