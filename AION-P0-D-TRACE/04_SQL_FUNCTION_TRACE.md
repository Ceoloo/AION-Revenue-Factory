# 04 — SQL Function / RPC Trace

Repository: **Ceoloo/AION-Revenue-Factory**

## Result: **No SQL, no RPC, no migrations, no triggers, no views**

**Confidence: HIGH (exhaustive negative evidence).**

The repository contains:

- **No `.sql` files.**
- **No migrations directory** (`supabase/migrations/`, `migrations/`, `db/`, `alembic/` — none exist).
- **No stored procedures, functions, triggers, views, or materialized views** defined in-repo.
- **No PostgREST `rpc` calls** — searched for `/rpc/`, `.rpc(`; zero matches.
- **No ORM / query builder** — no SQLAlchemy, no raw `SELECT`/`INSERT INTO` SQL strings. All persistence is REST `POST` (see `03_SUPABASE_DEPENDENCY_TRACE.md`).

Therefore none of the P0-D SQL sub-classifications apply within this repo:

| Question | Answer for AION-Revenue-Factory |
| --- | --- |
| Functions that READ legacy sources | none in-repo |
| Functions that WRITE legacy sources | none in-repo |
| Functions that READ canonical sources | none in-repo |
| Functions that WRITE canonical sources | none in-repo |
| BRIDGE legacy → canonical | none in-repo |
| BRIDGE canonical → legacy | none in-repo |

## Required per-function fields

```
FUNCTION:        (none)
SCHEMA:          N/A
FILE:            N/A
MIGRATION ROLE:  N/A — repository defines no database-side code
```

## Important caveat (declared)

Server-side SQL objects **may exist in the live Supabase project** (functions,
triggers, `pg_cron` jobs, RLS policies) that this repository writes into but does
not define. Confirming that requires either:

1. Read-only inspection of the Supabase project schema (out of scope for this
   code-only forensic pass; would use `list_tables` / `list_migrations` /
   `get_advisors` against the project), **and/or**
2. Scanning `aion-company-os` / `AION-VPS-Empire-Command.V1`, which are the likely
   owners of migrations and SQL functions.

Both are marked **UNRESOLVED** in `12_UNRESOLVED_DEPENDENCIES.md` and folded into
the Recommended Next P0.
