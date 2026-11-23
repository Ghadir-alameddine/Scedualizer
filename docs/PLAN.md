# Plan: Scedualizer - Multi-College Doctor Schedule Aggregator

## 1. Concept
A multi-tenant web app where doctors claim weekly teaching slots by clicking cells on a grid. The system aggregates all submissions into per-major-group timetables, detects conflicts (doctor double-booking, group collisions, capacity overruns), and auto-recommends resolutions based on workload fairness and minimum disruption. Admins view, approve, and export the final schedule.

## 2. Tech Stack
| Layer | Choice |
|---|---|
| Front-end | Streamlit (interactive grid + dashboards) |
| Back-end | Python (Streamlit native + Postgres only) |
| Database | PostgreSQL (shared, multi-tenant) |
| Auth | Per-tenant admin + doctor accounts, role-based |
| Delivery | SaaS (shared server) + optional Docker self-hosted |
| Billing | Stripe (freemium) |
## 3. Scheduling Workflow (3-Phase)

### Phase 1: Doctor Availability & Request
- Doctor logs in, sees their assigned courses
- For each course, an empty grid appears (rows = days Mon-Sat, cols = 75-min slots)
- Doctor clicks cells to mark availability - cells become "requested"
- Doctor can mark multiple slots per course; clicking again unmarks
- **Overlapping requests are allowed** - multiple doctors can request the same cell simultaneously. No uniqueness check at request time.
- Doctor hits "Submit" - requests are saved as pending entries
- Resubmissions: doctor can resubmit any time before the submission deadline. Previous requests are superseded (versioned), not deleted. The system diffs old vs. new and only re-runs conflict detection on changed cells.

### Phase 2: Conflict Detection & Recommendation
- After all doctors submit (or incrementally per doctor), the system runs the conflict engine
- **Uniqueness and conflict rules are enforced here, not at request time** - overlapping pending requests are expected and valid; the engine resolves them
- Conflicts are flagged in a panel for the admin
- The recommendation engine suggests optimal resolutions (see Section 6)
- Admin reviews, accepts/overrides recommendations

### Phase 3: Admin Approval & Lock
- Admin confirms entries (resolving conflicts) - only confirmed entries are subject to uniqueness constraints
- When all conflicts are resolved, admin "locks" the semester
- Locked schedule is the final output; any changes require unlocking (audit-logged)
- Export: multi-sheet Excel + PDF

### State Machine for Entries
```
requested -> pending -> confirmed -> locked
                 \-> rejected (by admin)
                 \-> superseded (by doctor resubmission)
```
- requested: doctor marked a cell, not yet submitted
- pending: doctor submitted, awaiting conflict check (overlaps allowed)
- confirmed: admin-approved, uniqueness enforced
- rejected: admin explicitly rejected this entry
- superseded: replaced by a newer resubmission (history preserved)
- locked: schedule is locked, changes require unlock

### Submission Deadlines (Not Auto-Delete)
- **No automatic deletion of pending requests.** Pending entries are preserved indefinitely as part of the scheduling history.
- Each tenant configures a **submission deadline** per semester (in `academic_calendars`)
- After the deadline, doctors can no longer submit new requests, but existing pending entries remain visible and can still be resolved by the admin
- Admin can extend the deadline or open a resubmission window if needed
- This preserves the full audit trail of what was requested, when, and how it was resolved
## 4. Cell Locking (Race-Condition-Safe, Overlap-Friendly)

### Design
- **No row-level locks on schedule_entries** - that would block legitimate overlapping requests
- **Overlapping pending requests are explicitly allowed** - multiple doctors can request the same (course, group, day, slot)
- Uniqueness is enforced **only at confirmation time** (Phase 3), not at request/submit time
- Atomic insert uses `ON CONFLICT (tenant_id, course_id, student_group_id, day, slot_index, doctor_id) DO NOTHING` - prevents the same doctor from submitting the same cell twice, but different doctors can coexist in `pending` state
- When a doctor clicks a cell:
  1. If free and no other pending requests - insert as pending
  2. If other pending requests exist on the same cell - still insert (overlap is valid), the conflict engine will resolve later
  3. If the doctor already has a pending entry on this cell - toggle off (delete)
  4. If the cell is confirmed by another doctor - show as locked, not clickable
- Cell occupancy query: `SELECT doctor_id, status FROM schedule_entries WHERE tenant_id=? AND course_id=? AND student_group_id=? AND day=? AND slot_index=?` - fast index, no lock held

### Race Condition Handling
- Two doctors click the same cell at the same moment:
  - Both run the atomic insert (different doctor_ids, so no conflict)
  - Both succeed - two pending requests now exist on the same cell
  - The conflict engine detects this in Phase 2 and recommends a resolution
  - No 409 errors, no blocking - overlapping requests are by design
- **No auto-expiry of pending requests.** Pending entries persist until the admin confirms or rejects them. The submission deadline controls when new requests can be made, not when old ones expire.

## 5. Database Schema (Improved Postgres Relationships)

### Tenants
- tenants - id, name, plan (free/paid), max_doctors, max_courses, academic_hours_per_slot, created_at
- academic_calendars - id, tenant_id, semester_name, start_date, end_date, days_of_week (JSONB), time_slots (JSONB), submission_deadline (timestamp), resubmission_deadline (timestamp, nullable), created_at
  - Configurable days and slot boundaries per semester
  - Submission deadline: after this, no new pending requests accepted
  - Resubmission deadline: optional window for doctors to resubmit before final lock

### People
- doctors - id, tenant_id, name, email, department, max_weekly_hours, is_active, created_at
- users - id, doctor_id (nullable), tenant_id, email, password_hash, role (admin/doctor/viewer), created_at
  - Admins: no doctor_id, can edit/export
  - Doctors: linked to a doctor record, can only see their own data
  - Viewers (paid): read-only access

### Academic Structure
- majors - id, tenant_id, name, year, created_at
- student_groups - id, tenant_id, major_id, name, student_count, created_at
  - A major has multiple student groups (e.g. "Group A", "Group B")
- courses - id, tenant_id, major_id, code, title, session_type (theory/lab), max_capacity, created_at
- course_group_assignments - id, course_id, student_group_id, created_at
  - A course can be assigned to multiple student groups
- course_hour_requirements - id, course_id, student_group_id, theory_weekly_hours (int, default 0), lab_weekly_hours (int, default 0), created_at
  - Per course + student group: how many theory and lab hours per week are required
  - Configurable by admin; if a course has no lab component, lab_weekly_hours = 0
  - Total required hours for a course-group = theory_weekly_hours + lab_weekly_hours

### Labs
- labs - id, tenant_id, course_id, student_group_id, instructor_doctor_id, lab_room_id (nullable), created_at
  - Links a specific lab session to a course + student group + instructor

### Scheduling
- schedule_entries - id, tenant_id, doctor_id, course_id, student_group_id, day, slot_index, session_type, status (requested/pending/confirmed/rejected/superseded/locked), version, created_at, updated_at, submitted_at
  - **No unique constraint at pending level** - multiple doctors can have pending entries on the same cell
  - Unique constraint only on (tenant_id, course_id, student_group_id, day, slot_index, doctor_id) for `confirmed` and `locked` statuses - enforced via partial index:
    `CREATE UNIQUE INDEX idx_confirmed_unique ON schedule_entries (tenant_id, course_id, student_group_id, day, slot_index, doctor_id) WHERE status IN ('confirmed', 'locked')`
  - Regular index for pending queries: (tenant_id, course_id, student_group_id, day, slot_index, status)
  - **History preserved**: superseded entries are not deleted, they are marked `superseded` and remain queryable for audit
- cell_requests - removed (replaced by schedule_entries with status=requested/pending - simpler, one table)

### Conflict Engine
- conflicts - id, tenant_id, conflict_type, entry_a_id, entry_b_id, description, severity, status (open/resolved/ignored), recommended_action (JSONB), resolved_by, resolved_at, created_at
- conflict_resolutions - id, conflict_id, action_taken (JSONB), recommended_by, applied_by, applied_at

### Audit
- audit_log - id, tenant_id, actor_id, action, entity_type, entity_id, before (JSONB), after (JSONB), created_at

### Usage (Billing)
- usage_metrics - tenant_id, doctor_count, course_count, entry_count, last_snapshot_at
  - Snapshot every 12 hours for freemium enforcement

### Key Relationships
tenant 1--N doctors
tenant 1--N majors
tenant 1--N academic_calendars (per semester)
major 1--N student_groups
major 1--N courses
course 1--N course_group_assignments
student_group 1--N course_group_assignments
course 1--N course_hour_requirements
student_group 1--N course_hour_requirements
course 1--N labs
student_group 1--N labs
doctor 1--N schedule_entries
course 1--N schedule_entries
student_group 1--N schedule_entries
schedule_entry 1--N conflicts
conflict 1--N conflict_resolutions
tenant 1--N usage_metrics
## 6. Conflict Engine (Hard Constraints + Explainable Scoring)

### Detection Types
1. **Doctor overlap** - same doctor, two confirmed entries in overlapping time slots
2. **Group collision** - same student group, two courses in the same time slot (students can't be in two places)
3. **Capacity exceeded** - doctor's confirmed weekly hours exceed max_weekly_hours
4. **Slot contention** - multiple doctors have pending requests on the same (course, group, day, slot) - resolved at confirmation time
5. **Incomplete course schedule** - a course-group has remaining unscheduled hours (required hours not yet met by confirmed entries). This is detected after all doctors submit and flagged for admin review.

### Hard Constraint Validation (Before Ranking)
Before any alternative slot is ranked, the system validates **hard constraints** - a slot that violates any of these is not eligible:
- Doctor has no other confirmed entry overlapping the proposed time
- Student group has no other confirmed entry overlapping the proposed time
- Doctor's total confirmed hours after adding this entry would not exceed max_weekly_hours
- If the entry is a lab: the lab room is free in the proposed slot
- The proposed day/slot exists in the tenant's academic calendar (not outside working hours)
- **Any slot that fails a hard constraint is excluded from ranking entirely** - no "close but not quite" recommendations

### Alternative Slot Ranking (Course Completion Priority)
When multiple doctors request the same cell, the system determines priority based on **which doctor's confirmation best completes required course hours**.


Step 1 - Calculate remaining unscheduled hours per course-group:
- For each (course, student_group), look up course_hour_requirements
- Sum confirmed entries: theory_scheduled = SUM of confirmed theory slots, lab_scheduled = SUM of confirmed lab slots
- remaining_theory = theory_weekly_hours - theory_scheduled
- remaining_lab = lab_weekly_hours - lab_scheduled
- If remaining <= 0 for both, the course-group is complete

Step 2 - Score each requesting doctor for the contested cell:
- A doctor gets the cell if confirming their entry reduces the total remaining hours for that course-group
- If two doctors request the same cell for the same course-group, the one whose confirmation leaves fewer remaining hours wins
- If both doctors' entries complete the same amount, prefer the one with fewer total remaining hours across ALL their assigned course-groups (fairness: help the doctor who is furthest from complete first)

Step 3 - Lexicographic ranking for alternative slots:
- Primary: remaining hours reduction for the contested course-group (more is better)
- Secondary: total remaining hours across the doctor's full assignment (lower is better - fairness)
- Tertiary: fewest new conflicts created
- Quaternary: distance from doctor's nearest existing entry that day

No arbitrary weights. The ranking is explainable:
- "Dr X gets this slot because it completes 2 of 3 remaining theory hours for CS201/Gr A, and Dr X still has 5 unscheduled hours while Dr Y has only 1 remaining."
- "Moving Dr Y to Thu 14:15-15:30 keeps 0 new conflicts and is adjacent to their existing entry."

Admin sees a one-sentence explanation with the remaining-hours numbers.

### Recommendation Output
For each open conflict, the engine produces:
- recommended_action: { move_entry_id, to_day, to_slot, reason (human-readable explanation) }
- alternatives: top 3 eligible slots with their conflict count and load impact
- severity: high (blocks 2+ doctors), medium (1 doctor blocked), low (cosmetic)
- Admin sees the panel sorted by severity, can accept/override/reassign

## 7. Weekly Hours Calculation (Accurate, No Saturday Penalty)

### Configurable Academic Hours
- `tenants.academic_hours_per_slot` - how many academic hours one slot represents (default: 1.0, configurable per tenant)
- `academic_calendars.time_slots` - per-semester slot definitions (75-min default, configurable: 60-min, 90-min, etc.)
- `doctors.max_weekly_hours` - cap per doctor (in academic hours)

### Calculation
- Each confirmed schedule_entry contributes exactly `academic_hours_per_slot` to the doctor's weekly total
- `weekly_hours(doctor) = SUM(academic_hours_per_slot) WHERE doctor_id=? AND status IN ('confirmed','locked')`
- **Saturday sessions count the same as weekday sessions** - no multiplier, no penalty. A 75-min Saturday session = 1.0 academic hour, same as a 75-min Monday session.
- If a tenant wants different slot lengths on Saturday, they configure `time_slots` per day in the academic calendar - the hour count is derived from slot duration, not a Saturday discount

### Course Completion Tracking
- For each (course, student_group), track scheduled vs. required hours:
  - theory_scheduled = count of confirmed theory slots * academic_hours_per_slot
  - lab_scheduled = count of confirmed lab slots * academic_hours_per_slot
  - theory_remaining = theory_weekly_hours - theory_scheduled
  - lab_remaining = lab_weekly_hours - lab_scheduled
- A course-group is **complete** when theory_remaining <= 0 AND lab_remaining <= 0
- An **incomplete schedule warning** is shown to admin when any course-group has remaining hours > 0 after all doctors have submitted
- The admin dashboard shows a list of incomplete course-groups with their remaining hours

### Load Dashboard
- Bar chart of each doctor's confirmed hours vs. cap
- Color-coded: green (under 80%), yellow (80-100%), red (over 100%)
- **Fairness metric**: coefficient of variation (CV = std_dev / mean) across all doctors - lower is more balanced
- No arbitrary fairness weighting in the conflict engine - CV is informational only
- **Course completion rate**: percentage of course-groups that are fully scheduled (informational, drives admin urgency)

## 8. Security (Strict Multi-Tenant Isolation)

### Tenant Isolation
- Every table has tenant_id - all queries are scoped by it
- Row-Level Security (RLS) in PostgreSQL: CREATE POLICY tenant_isolation ON <table> USING (tenant_id = current_setting('app.tenant_id')::int)
  - Enforced at the DB level, not just the app layer
  - Even if the app has a bug, cross-tenant data is inaccessible
- Session context: on login, the app sets SET app.tenant_id = <tenant> for the session
- No tenant_id in the URL - all access is via authenticated session

### Authentication
- Per-tenant admin + doctor accounts
- Password hashing: bcrypt (or argon2)
- Session-based: signed JWT cookies, 8-hour expiry, refresh on activity
- Optional 2FA for admins (paid tier feature)

### Role-Based Permissions
| Role | Permissions |
|---|---|
| Admin | CRUD doctors/courses/groups, set course hour requirements (theory + lab per group), resolve conflicts, confirm/lock schedule, export, view audit log, manage tenant settings, set deadlines, view incomplete course warnings |
| Doctor | View own courses, mark availability, resubmit own schedule, view own conflicts, view per-doctor card |
| Viewer (paid) | Read-only access to confirmed timetables, export |

### Cross-Tenant Access
- Hard 403, not just UI hiding
- RLS policies prevent even DB-level cross-tenant reads
- Audit log records every access attempt with actor + tenant

### Data Isolation Summary
- Shared DB (one PostgreSQL instance)
- tenant_id on every table
- Row-Level Security enforced in PostgreSQL
- Session context set on login
- No cross-tenant queries possible even if app layer is bypassed
## 9. Grid (Streamlit Interactive Selection)

### Approach
- Streamlit is re-render-based, so use st.data_editor with a custom cell renderer for the click-to-mark grid
- Each cell is a toggle: click = mark as requested, click again = unmark
- **Overlapping requests are valid** - the UI shows other doctors' pending requests as "contested" (orange border) but still allows the current doctor to click
- State management: st.session_state holds the current doctor's draft (requested cells) until they hit "Submit"
- Concurrency: each doctor has their own session, so concurrent users don't interfere in the UI. The backend atomic insert handles the "two doctors, same cell" case by allowing both pending entries
- Real-time updates: when admin confirms or rejects, the doctor's next page load reflects the change (no WebSocket needed for MVP)

### Cell States (Visual)
| State | Visual | Meaning |
|---|---|---|
| Empty | White, clickable | No one has requested this cell |
| Requested (mine) | Blue border, "Yours" badge | I have a pending request here |
| Contested | Orange border, "Dr X, Dr Y requested" badge | Multiple doctors have pending requests - will be resolved at confirmation |
| Locked (confirmed other) | Gray, "Dr X" badge, not clickable | Confirmed by another doctor, no longer available |
| Confirmed (mine) | Green, checkmark | My entry is confirmed |
| Rejected | Red, X mark | My request was rejected by admin |

### Streamlit Limitations & Workarounds
- st.data_editor is re-render-based: clicking a cell triggers a full page refresh. For under 50 doctors, this is fine. For 200+, may need a custom HTML/JS grid with st.components (deferred to post-MVP if needed)
- No WebSocket in Streamlit MVP: real-time updates are on next page load. Acceptable for weekly scheduling cycles
- Mobile: Streamlit is responsive, but the grid may need horizontal scroll on phones. Acceptable for MVP

## 10. Freemium & Billing

### Free Tier
- 1 college, 50 doctors, 100 courses
- Core: click-to-mark grid, conflict detection, per-major grid, Excel export
- No: load balancing dashboard, PDF export, audit log, API, 2FA

### Paid Tier
- Unlimited doctors/courses
- Load balancing dashboard, PDF export, audit log, API access, 2FA, priority support
- Billing: Stripe subscription (monthly/annual)
- Usage snapshot every 12h - if over free limits, auto-downgrade features (not data loss)

## 11. Delivery: SaaS + Self-Hosted

### SaaS (Primary)
- One shared server, all colleges
- Auto-updated, managed DB backups
- Stripe billing

### Self-Hosted (Optional, Paid)
- Docker container + PostgreSQL
- Same codebase, single-tenant mode (no tenant_id scoping needed)
- For colleges that need on-prem data control

## 12. Output Format (from demo image)

### Grid Orientation
- Days are rows (Mon -> Fri, plus a distinct Saturday section)
- Time slots are columns - 75-minute sessions (configurable)
- Each sheet = one major-group, e.g. "Fall 2026/2027 - Year 3 - Group 2"
- The same doctor legitimately appears in multiple sheets

### Cell Model
- Each cell can hold multiple items - e.g. a theory course + a lab, or two group labs in the same 75-min window
- Stacked sub-cells rendered vertically
- Empty cells = no session
- Only confirmed/locked entries appear in the output grid (pending requests are not shown in the final timetable)

### Color Coding (match the demo)
| Color | Meaning |
|---|---|
| White | Theory session |
| Yellow | Lab session |
| Gray/red text | Saturday (distinct section, lower priority) |
| (admin can add more) | e.g. green for optional, orange for make-up classes |

### Per-Doctor Card View
- In addition to the per-major grid, each doctor gets a card listing all their confirmed courses grouped by major, with week total hours

### Header
- Sheet title: {Semester} - {Year} Year: {Group}

## 13. MVP Build Order (Updated)

### Phase 1: Foundation (Week 1-2)
1. Multi-tenant schema (all tables with tenant_id) + RLS policies + partial unique index for confirmed entries
2. Auth: per-tenant admin + doctor accounts, session-based
3. Academic calendar config (days, slots, submission deadline) per semester
4. CRUD: doctors, majors, student_groups, courses, labs, course_hour_requirements (theory + lab hours per group)

### Phase 2: Input (Week 3-4)
5. Click-to-mark grid with st.data_editor + st.session_state draft
6. Atomic insert with ON CONFLICT (allows overlapping pending requests, prevents duplicate same-doctor entries)
7. Contested cell visual (orange border, shows all requesting doctors)
8. Submit flow: save pending entries, run conflict detection on overlap + hard constraints

### Phase 3: Conflict Engine (Week 5-6)
9. Conflict detection: doctor overlap, group collision, capacity, slot contention, incomplete course schedule
10. Hard constraint validation (exclude ineligible slots before ranking)
11. Course-completion priority ranking: remaining hours reduction, fairness tiebreaker, fewest new conflicts, proximity
12. Conflict panel for admin (sorted by severity, explainable recommendations with remaining-hours numbers, accept/override/reassign)
13. Weekly hours calculation (uniform, no Saturday penalty) + course completion tracking + load dashboard
14. Incomplete schedule warning panel for admin (list of course-groups with remaining hours)

### Phase 4: Output (Week 7-8)
15. Per-major-group grid (color-coded, stacked sub-cells, confirmed entries only)
16. Per-doctor card view
17. Multi-sheet Excel export + PDF export
18. Admin confirm/lock + audit log + submission deadline enforcement

### Phase 5: SaaS & Billing (Week 9-10)
19. Freemium enforcement (usage limits, auto-downgrade)
20. Stripe integration (subscription billing)
21. Docker packaging (self-hosted option)

## 14. Decisions Made
- Input: click-to-mark grid, overlapping pending requests allowed, uniqueness enforced only at confirmation
- No auto-delete of pending requests: configurable submission deadlines, full history preserved
- Weekly hours: uniform counting (Saturday = same as weekday, no multiplier), derived from slot duration
- Conflict engine: hard constraint validation first, then course-completion priority ranking (no arbitrary weights). Priority = which doctor's confirmation best reduces remaining unscheduled hours for the contested course-group, with fairness as tiebreaker
- Course hour requirements: per course + student group, theory and lab hours tracked separately, admin-configurable
- Incomplete schedule detection: flagged when any course-group has remaining hours > 0 after all submissions
- Sheet granularity: per major-group, matching the demo
- Cell colors: white=theory, yellow=lab, gray/red=Saturday
- Security: PostgreSQL RLS + session-based auth + role-based permissions
- Database: PostgreSQL, shared multi-tenant with RLS
- Platform: Streamlit, SaaS + Docker self-hosted
- Scope: MVP-focused, 10-week build

## 15. Open Questions (Remaining)
- Freemium caps - 50 doctors / 100 courses reasonable? Or scale by semester size?
- Rooms - track room allocation in MVP, or post-MVP?
- LLM fallback - keep the optional text-paste feature, or drop entirely?
- 2FA - paid-tier only, or free-tier too?
- Resubmission window - separate deadline from submission deadline, or same?