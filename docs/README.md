# Unicorn Viz Documentation Index

Owner: Studio Documentation
Status: active
Last updated: 2026-05-24

This is the canonical map for project documentation.

## Product Documentation

- [User Guide](user-guide.md)
- [Configuration Reference](configuration.md)
- [Effect Settings Reference](effect-settings.md)
- [Developer Guide](developer-guide.md)
- [Testing Guide](testing.md)
- [Drop-in Documentation Registry](drop-ins.md)
- [Marketing](marketing/README.md)

## Working Documentation

- Planning: [docs/planning](planning)
- Auto VJ training protocol: [docs/planning/auto-vj-training-pack-protocol.md](planning/auto-vj-training-pack-protocol.md)
- Hotkey architecture refactor: [docs/planning/hotkey-architecture-refactor.md](planning/hotkey-architecture-refactor.md)
- Hotkey cross-platform conflict remap plan (2026-06-03): [docs/planning/hotkey-cross-platform-conflict-remap-plan-2026-06-03.md](planning/hotkey-cross-platform-conflict-remap-plan-2026-06-03.md)
- Debug and handoff notes: [docs/debug](debug)
- Audit reports and review snapshots: [docs/audits](audits)
  - Full system audit (2026-06-01): [docs/audits/2026-06-01-system-audit.md](audits/2026-06-01-system-audit.md)
  - Hotkey refactor P0 hotfix brief (2026-06-01): [docs/audits/2026-06-01-hotkey-refactor-regressions.md](audits/2026-06-01-hotkey-refactor-regressions.md)
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
