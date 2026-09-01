---
name: supabase-etiquette
description: >-
  Lasmuns Supabase migration etiquette for local vs hosted, MCP apply_migration
  stamps, db reset, and migration repair. Use when adding, deleting, applying,
  or pushing supabase/migrations, running db reset / db push / migration
  repair / migration list, or using apply_migration MCP.
disable-model-invocation: false
---

# Supabase etiquette (lasmuns)

Official CLI: [cli-workflows](https://supabase.com/docs/guides/local-development/cli-workflows), [database-migrations](https://supabase.com/docs/guides/deployment/database-migrations).

## Migration filename stamps

`YYYYMMDDHHMMSS` (14 digits, UTC, second precision). Without the CLI:

```bash
TZ=UTC date +%Y%m%d%H%M%S
touch "supabase/migrations/$(TZ=UTC date +%Y%m%d%H%M%S)_name.sql"
```

## Production migrations — explicit approval required

**Do not push or apply migrations to production (linked remote / MCP `apply_migration` on production) unless the user explicitly asks.**

- Local only by default: `supabase db query --local`, `supabase db reset`, edit + test migrations locally first.
- **`supabase db push --linked`**, **`apply_migration`** on the production MCP namespace, and any service-role SQL that changes hosted schema/data are production writes — stop and ask.
- Exception: the user says “push to production”, “apply on remote”, “ship the migration”, or similar clear approval in the same turn.
- Config-only updates (e.g. `push_config` upsert via script) are still production writes; same rule unless the user approved that specific change.

## Local vs linked

Pass `--local` or `--linked` explicitly. Defaults differ: `db reset` / `db diff` → local; `db push` / `db pull` / `db dump` → linked.

| Command | Effect |
|---|---|
| `supabase db reset` | Destroy **local** DB, replay `supabase/migrations/` + seed |
| `supabase db reset --linked` | Destroy **linked remote**, replay local files. Never production |
| `supabase db push` | Apply local files missing from remote `supabase_migrations.schema_migrations` |
| `supabase migration list` | Compare files vs history rows (local and/or linked) |
| `supabase migration repair --status applied\|reverted <version>` | Edit **history rows only**. Does not undo or run SQL |

Local can `db reset` anytime. Safe to **delete** a file you never want hosted to run. Do not keep landmines “because local applied them.” After delete: reset, or `repair --local --status reverted <version>` if the row exists so `migration list` is clean.

## Never `db push` a landmine

`db push` runs every local file not in hosted history. If a file must not run on hosted (e.g. mass `store_manager` → `super_admin`), delete it first. Do not rely on a header comment.

## MCP `apply_migration` vs files

`apply_migration` MCP stamps **now**, not the filename version → GitHub “remote versions not found.” Prefer `supabase migration` CLI / files with stable versions over MCP apply for anything that must stay in git history. Dashboard MCP applies on hosted create extra remote-only versions.

## This project

Shared hosted project with `../lasmuns-university` (`rsrunodvijqucecsfpuy`). University files may not be on hosted; extras on hosted were dashboard MCP applies.

- **20100** (`pin_login_roles_rls`) — example landmine. Promotes every `store_manager` → `super_admin`. Hosted never had it. Deleted; do not reintroduce or apply.
- **20400** — safe RLS cutover (no role UPDATE). Hosted cutover.
- **20200 / 20300** — may still be pending locally vs hosted. Check `migration list` before push; do not assume they ran remotely.
