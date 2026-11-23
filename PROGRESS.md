# Scedualizer — Progress Tracker

Tracks the state of every task in `ROADMAP.md`. Update a task's status as work happens.

Legend:
- `[ ]` pending — not started
- `[~]` in progress — started, not complete
- `[x]` done — complete and verified against the task's "Done when" criteria

## Phase 0 — Project Scaffold & Configuration
- [x] T0.1 Repository & Python project scaffold
- [ ] T0.2 Application settings & multi-tenant mode

## Phase 1 — Foundation: Schema, RLS, Auth, CRUD
- [ ] T1.1 SQLAlchemy models for the full multi-tenant schema
- [ ] T1.2 Alembic initial migration + partial unique index
- [ ] T1.3 Database session factory & RLS tenant scoping
- [ ] T1.4 Auth: users, roles, password hashing, JWT session cookies
- [ ] T1.5 Tenant & academic calendar CRUD + submission deadlines
- [ ] T1.6 Academic structure CRUD (doctors, majors, groups, courses, labs, hour requirements)

## Phase 2 — Input: Click-to-Mark Grid & Submit Flow
- [ ] T2.1 `st.data_editor` click-to-mark grid + session-state draft
- [ ] T2.2 Atomic insert of pending entries (overlap-friendly)
- [ ] T2.3 Contested-cell visual + submit-time conflict trigger

## Phase 3 — Conflict Engine & Recommendation
- [ ] T3.1 Conflict detection (5 types)
- [ ] T3.2 Hard-constraint validation (gate before ranking)
- [ ] T3.3 Course-completion-priority ranking
- [ ] T3.4 Admin conflict panel + accept/override/reassign
- [ ] T3.5 Weekly hours + course completion + load dashboard

## Phase 4 — Output: Timetables, Export, Lock & Audit
- [ ] T4.1 Per-major-group color-coded grid with stacked sub-cells
- [ ] T4.2 Per-doctor card view
- [ ] T4.3 Multi-sheet Excel + PDF export
- [ ] T4.4 Admin confirm/lock + audit log + deadline enforcement

## Phase 5 — SaaS & Billing
- [ ] T5.1 Freemium enforcement (usage snapshots, auto-downgrade)
- [ ] T5.2 Stripe subscription integration
- [ ] T5.3 Docker packaging (self-hosted option)

## Cross-Cutting
- [ ] pytest suite per service
- [ ] ruff + mypy clean

## Current Focus
- **Next task:** T0.2 — Application settings & multi-tenant mode

## Changelog
- 2026-11-23 — Initialized roadmap and progress tracker from `docs/PLAN.md`.
- 2026-11-23 — T0.1 complete: modular package layout (`config/`, `data/{db,models}`, `auth/`, `services/`, `apps/`), dev extras (pytest, ruff, mypy), `.env.example`, smoke tests (9 passed), ruff check + format clean.
