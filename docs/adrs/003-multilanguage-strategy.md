# ADR-003: Multi-language Documentation Strategy

**Status:** Accepted
**Date:** 2026-03-07 (migrated from .txt)

## Context

Maestro aims to be globally accessible as an open source project while maintaining
a strong base of Portuguese-speaking contributors and users.

## Decision

| Scope | Language |
|-------|----------|
| Primary documentation | English (en-US) |
| Secondary documentation | Portuguese Brazilian (pt-BR) |
| Source code (variables, functions, internal comments) | English exclusively |
| User documentation (README) | Bilingual — EN primary, PT-BR secondary |
| ADRs and internal technical docs | May start in PT-BR; migrate to EN as the project scales |

## File Naming Convention

- Primary file (e.g. `README.md`) must be in English.
- Portuguese Brazilian translations use the `.pt-BR.md` suffix.
- Example: `README.md` (English) and `README.pt-BR.md` (Portuguese).

## Motivation

- English is the de facto standard in the global tech community and open source ecosystem.
- Portuguese Brazilian is maintained to support the local community and ease regional developer onboarding.

## Consequences

- No language barrier for international contributions.
- Local community onboarding remains friction-free.
- ADRs created in PT-BR (legacy) must be migrated to EN during Phase 2.
  This ADR itself is the first example of that migration.
