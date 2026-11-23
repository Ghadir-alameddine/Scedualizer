# Scedualizer — Development Roadmap

This roadmap breaks the plan in `docs/PLAN.md` into small, ordered, testable tasks. Each task has:
- **Depends on** — tasks that must be done first
- **Deliverables** — files / code / artifacts produced
- **Done when** — concrete, verifiable completion criteria

The architecture is modular and layered so each concern can be developed, tested, and changed independently:

```
streamlit UI (apps/)
      |
   services/   (business logic: conflicts, recommendation, weekly hours, export)
      |
   data/
   ├── db/      (SQLAlchemy engine, session, RLS tenant scoping)
   └── models/  (ORM models + Alembic migrations)
      |
   auth/        (tenants, users, roles, JWT session cookies, passwords)
      |
   config/      (settings, multi-tenant / self-hosted mode)
```

Key invariants applied throughout:
- Every table has `tenant_id`; every DB query is tenant-scoped; RLS is the DB-level backstop.
- Conflict / recommendation / weekly-hours logic lives in **pure, unit-testable service modules** — no Streamlit or SQL coupling.
- Overlapping pending requests are **by design**; uniqueness is enforced only on `confirmed` / `locked` via a partial unique index.
- No automatic deletion of pending entries; history is preserved.

---

## Phase 0 — Project Scaffold & Configuration

### T0.1 — Repository & Python project scaffold
- **Depends on:** —
- **Deliverables:** `src/scedualizer/__init__.py` package; modular sub-packages (`config/`, `data/`, `auth/`, `services/`, `apps/`); `pyproject.toml` with dev extras (pytest, ruff, mypy); `.python-version`; `.env.example`.
- **Done when:**
  - `uv sync` succeeds; `uv run python -c "import scedualizer"` succeeds.
  - Directory tree matches the module layout above.
  - `uv run pytest` runs (0 tests is fine) and `uv run ruff check .` passes.

### T0.2 — Application settings & multi-tenant mode
- **Depends on:** T0.1
- **Deliverables:** `config/settings.py` (Pydantic-style or dataclass settings reading from env): `DATABASE_URL`, `JWT_SECRET`, `SELF_HOSTED` (single-tenant mode flag), tier flag. `config/__init__.py`.
- **Done when:**
  - Settings load from `.env` with sensible dev defaults.
  - A `load_settings()` unit test verifies env overrides and the `SELF_HOSTED` boolean.

---

## Phase 1 — Foundation: Schema, RLS, Auth, CRUD

### T1.1 — SQLAlchemy models for the full multi-tenant schema
- **Depends on:** T0.1
- **Deliverables:** `data/models/` ORM models for: `tenants`, `academic_calendars`, `doctors`, `users`, `majors`, `student_groups`, `courses`, `course_group_assignments`, `course_hour_requirements`, `labs`, `schedule_entries`, `conflicts`, `conflict_resolutions`, `audit_log`, `usage_metrics`. Enum for entry status; JSONB fields where the plan specifies.
- **Done when:**
  - Models import cleanly; `Base.metadata` contains all 15 tables; each table has a `tenant_id` column (except `usage_metrics` which is keyed by it).
  - A test instantiates `metadata.create_all` on an in-memory Postgres (or SQLite-compatible subset) and asserts table + column presence.

### T1.2 — Alembic initial migration + partial unique index
- **Depends on:** T1.1
- **Deliverables:** Alembic env wired to `config`; `versions/0001_initial.py` creating all tables, indexes, and the **partial unique index** `idx_confirmed_unique ... WHERE status IN ('confirmed','locked')`; regular index for pending-cell queries.
- **Done when:**
  - `alembic upgrade head` succeeds on a clean Postgres.
  - The partial unique index exists (verified via `information_schema`/`\di` query in a test or manual check).

### T1.3 — Database session factory & RLS tenant scoping
- **Depends on:** T1.1
- **Deliverables:** `data/db.py` — engine + `SessionLocal` factory; `set_tenant(session, tenant_id)` that issues `SET LOCAL app.tenant_id`; RLS policies for every table (`USING (tenant_id = current_setting('app.tenant_id')::int)`); `self-hosted` mode skips RLS.
- **Done when:**
  - Unit/integration test proves a session scoped to tenant A cannot read tenant B rows (RLS test) — or in self-hosted mode, no scoping is applied.

### T1.4 — Auth: users, roles, password hashing, JWT session cookies
- **Depends on:** T1.2, T1.3
- **Deliverables:** `auth/passwords.py` (bcrypt/argon2), `auth/jwt.py` (sign/verify, 8 h expiry, refresh-on-activity), `auth/deps.py` (current-user resolver, role guards), `users` seed/admin bootstrap.
- **Done when:**
  - Unit tests cover: hash+verify, JWT sign/verify, expiry rejection, role-guard 403 paths.
  - Cross-tenant access is hard-rejected (not just hidden in UI).

### T1.5 — Tenant & academic calendar CRUD + submission deadlines
- **Depends on:** T1.4
- **Deliverables:** `services/tenants.py`, `services/calendars.py`; per-semester days/slots/submission + resubmission deadlines; deadline enforcement helper.
- **Done when:**
  - Tests create a tenant, calendar, and verify that after the deadline, new pending requests are rejected (deadline gate) while existing pending entries remain visible.

### T1.6 — Academic structure CRUD (doctors, majors, groups, courses, labs, hour requirements)
- **Depends on:** T1.5
- **Deliverables:** `services/academics.py` covering all of the above, including per-course-group theory + lab hour requirements.
- **Done when:**
  - CRUD round-trip tests succeed; hour requirements can be set to 0 for lab-only/theory-only courses.

---

## Phase 2 — Input: Click-to-Mark Grid & Submit Flow

### T2.1 — `st.data_editor` click-to-mark grid + session-state draft
- **Depends on:** T1.6
- **Deliverables:** `apps/doctor_grid.py` — grid (rows = days, cols = 75-min slots), toggle-on/off, draft held in `st.session_state` until **Submit**.
- **Done when:**
  - Manual/UI test: clicking a cell toggles it blue ("Yours"); re-clicking unmarks; draft survives page re-render; "Submit" persists.

### T2.2 — Atomic insert of pending entries (overlap-friendly)
- **Depends on:** T2.1
- **Deliverables:** `services/entries.py` — `ON CONFLICT (tenant, course, group, day, slot, doctor) DO NOTHING` insert; toggle-off deletes the doctor's own pending entry; occupied-by-other-doctor cells render as locked/not-clickable.
- **Done when:**
  - Concurrent "two doctors, same cell" test: both inserts succeed (two pending rows). Same-doctor double-insert is de-duplicated.

### T2.3 — Contested-cell visual + submit-time conflict trigger
- **Depends on:** T2.2, T3.1 (detection)
- **Deliverables:** Orange "contested" border listing requesting doctors; on submit, run incremental conflict detection on changed cells only.
- **Done when:**
  - UI shows contested cells with all requesters; submit triggers detection without re-checking unchanged cells.

---

## Phase 3 — Conflict Engine & Recommendation

### T3.1 — Conflict detection (5 types)
- **Depends on:** T2.2
- **Deliverables:** `services/conflicts.py` — doctor overlap, group collision, capacity overrun, slot contention, incomplete course schedule. Pure functions over entry rows; writes to `conflicts` table.
- **Done when:**
  - Each of the 5 types has a focused unit test that produces a conflict row with the correct `conflict_type` + `severity`.

### T3.2 — Hard-constraint validation (gate before ranking)
- **Depends on:** T3.1
- **Deliverables:** `services/constraints.py` — returns the set of **eligible** alternative slots for an entry; any slot violating a hard constraint is excluded, not ranked.
- **Done when:**
  - Tests assert that a slot failing any hard constraint (overlap, group collision, capacity, lab-room, outside calendar) is absent from the candidate set.

### T3.3 — Course-completion-priority ranking
- **Depends on:** T3.2
- **Deliverables:** `services/recommendation.py` — remaining-hours calculation; lexicographic ranking (primary: reduction of remaining hours for the contested course-group; secondary: doctor's total remaining hours / fairness; tertiary: fewest new conflicts; quaternary: proximity to nearest same-day entry). Emits `recommended_action` + top-3 `alternatives` + one-sentence `reason`.
- **Done when:**
  - Deterministic unit tests: given a fixed scenario, the top recommendation matches the expected doctor + slot, and the `reason` string contains the concrete remaining-hours numbers (explainable, no arbitrary weights).

### T3.4 — Admin conflict panel + accept/override/reassign
- **Depends on:** T3.3
- **Deliverables:** `apps/admin_conflicts.py` — severity-sorted panel; accept/override/reassign actions persisted to `conflict_resolutions`.
- **Done when:**
  - Panel renders conflicts by severity; accepting a recommendation applies the move and writes a resolution row; overrides are audit-logged.

### T3.5 — Weekly hours + course completion + load dashboard
- **Depends on:** T3.3
- **Deliverables:** `services/weekly_hours.py` (uniform counting, no Saturday penalty; per-course-group completion tracking) + `apps/load_dashboard.py` (doctor load bars, CV fairness metric, course-completion rate, incomplete-schedule warning panel).
- **Done when:**
  - Saturday slots count identically to weekdays in tests; dashboard shows green/yellow/red thresholds and the CV value; incomplete course-groups listed with remaining hours.

---

## Phase 4 — Output: Timetables, Export, Lock & Audit

### T4.1 — Per-major-group color-coded grid with stacked sub-cells
- **Depends on:** T3.5
- **Deliverables:** `apps/timetable.py` + `services/export/grid.py` — one sheet per major-group; white=theory, yellow=lab, gray/red=Saturday; stacked sub-cells; **confirmed/locked entries only**.
- **Done when:**
  - A fixture tenant renders a correct per-major sheet matching the demo orientation; pending entries are excluded.

### T4.2 — Per-doctor card view
- **Depends on:** T4.1
- **Deliverables:** `apps/doctor_card.py` — doctor's confirmed courses grouped by major, with week total hours.
- **Done when:** Hours on the card equal the `weekly_hours` service output for that doctor.

### T4.3 — Multi-sheet Excel + PDF export
- **Depends on:** T4.1
- **Deliverables:** `services/export/excel.py`, `services/export/pdf.py`; one workbook/sheet per major-group.
- **Done when:** Export produces a valid multi-sheet Excel and PDF for a fixture tenant; only confirmed/locked entries present.

### T4.4 — Admin confirm/lock + audit log + deadline enforcement
- **Depends on:** T4.3
- **Deliverables:** `services/lifecycle.py` — confirm (enforces partial unique index), lock/unlock (audit-logged); `audit_log` writes for actor + tenant + before/after JSONB.
- **Done when:**
  - Locking blocks further edits without unlock; every lock/unlock/resolution is in `audit_log`; deadline gate still enforced.

---

## Phase 5 — SaaS & Billing

### T5.1 — Freemium enforcement (usage snapshots, auto-downgrade)
- **Depends on:** T4.4
- **Deliverables:** `services/billing.py` + `usage_metrics` 12-hour snapshot; over-limit tenants auto-downgrade features (not data loss).
- **Done when:** A tenant exceeding free caps has paid-only features (load dashboard, PDF export, audit log, API, 2FA) disabled; data is intact.

### T5.2 — Stripe subscription integration
- **Depends on:** T5.1
- **Deliverables:** Stripe customer/subscription wiring; plan sync to `tenants.plan`; 2FA as a paid-tier feature.
- **Done when:** A subscription change updates the tenant plan; feature gating follows the new plan.

### T5.3 — Docker packaging (self-hosted option)
- **Depends on:** T5.2
- **Deliverables:** `Dockerfile` + `docker-compose.yml` (app + Postgres); `SELF_HOSTED` single-tenant mode.
- **Done when:** `docker compose up` brings up a working single-tenant instance with no `tenant_id` scoping required.

---

## Cross-Cutting Quality Gates
- **Tests:** pytest suite per service (conflict, constraint, recommendation, weekly hours, export, billing) — services stay free of UI/SQL coupling where practical.
- **Lint/Format:** `ruff` (format + lint) and `mypy` clean before each phase merge.
- **Docs:** each service module carries a short docstring explaining its pure-function contract.

## Suggested Working Sequence
Execute tasks strictly in the order above (T0.1 → T5.3), one task at a time. Each task is sized to be completable and verifiable in isolation before moving on. Phases 1–4 are the MVP core; Phase 5 is SaaS/billing.
