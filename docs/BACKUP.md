# Backup & restore

A backup nobody has restored is a belief, not a capability. This page covers both halves: the
nightly dump, and the **drill** that restores it into a throwaway database every week and fails
loudly when it can't.

Applies to the Docker Compose production stack (`compose.prod.yml`: Postgres 17 in the `db`
service, data on the `provekit-pg` volume). See [DEPLOY.md](DEPLOY.md) for the stack itself.

---

## TL;DR

```bash
bash deploy/install-backups.sh    # installs both crons (daily dump 03:15, weekly drill 03:40 Sun)

# then, once, before you trust any of it:
BACKUP_DIR=/root/provekit-backups bash deploy/backup.sh
BACKUP_DIR=/root/provekit-backups bash deploy/verify-restore.sh
```

The drill exits `0` only if the newest dump restores into a fresh database that has the right
tables, non-zero rows, and an `alembic_version` matching the schema your deployed code expects.

---

## The four scripts

| Script | What it does | Touches production data? |
|---|---|---|
| `deploy/backup.sh` | `pg_dump` from the `db` container → gzip in `BACKUP_DIR`, prune past `RETAIN_DAYS` | reads only |
| `deploy/verify-restore.sh` | restores the newest dump into a **throwaway** database, asserts it, drops it | no — creates and drops its own database |
| `deploy/restore.sh` | restores a dump into a named database; refuses to clobber without `--force` | only with `--force` |
| `deploy/install-backups.sh` | installs the two cron jobs | no |

### backup.sh

```bash
BACKUP_DIR=/root/provekit-backups RETAIN_DAYS=7 bash deploy/backup.sh
```

Env: `BACKUP_DIR`, `RETAIN_DAYS`, `DB_CONTAINER` (default `provekit-db-1`), `DB_USER`, `DB_NAME`.

Writes `provekit-YYYYMMDD-HHMMSS.sql.gz`, a `.sha256` sidecar, and refreshes a
`provekit-latest.sql.gz` symlink. The dump lands as `.part` first and is only renamed after
`gzip -t` passes — a dump killed halfway by a full disk or a container restart otherwise leaves
a file that looks exactly like a backup, and you find out it is half a database on the day you
need it. The dump uses `--no-owner --no-privileges` so it can be restored into the drill
database, or onto a rebuilt host whose role names differ.

### verify-restore.sh — the drill

```bash
BACKUP_DIR=/root/provekit-backups bash deploy/verify-restore.sh
```

It creates `provekit_drill_<timestamp>_<pid>` in the same Postgres server, restores the newest
dump into it, runs the assertions below, and drops it again (via an `EXIT`/`INT`/`TERM` trap, so
an interrupted drill doesn't leave a full copy of production sitting next to production).

| Assertion | Why it is there |
|---|---|
| dump is younger than `MAX_AGE_HOURS` (default 36) | a drill that passes weekly against the same six-month-old file proves the restore path works and hides that you've been losing data since March |
| dump is at least `MIN_BYTES` (default 1024) | a 300-byte dump is a failed `pg_dump`, not a small database |
| `gzip -t` + `.sha256` match (in `restore.sh`) | silent bit rot on the backup volume |
| core tables present (`alembic_version`, `workspaces`, `users`, `runs`, `api_keys`, `workspace_members`) | catches a dump of the wrong database entirely |
| `runs` and `workspaces` have ≥ `MIN_ROWS` rows (default 1) | a dump of an empty database restores perfectly and proves nothing |
| exactly one `alembic_version` row, equal to head | a dump taken mid-migration, or from a hand-rebuilt database, restores into something the deployed code won't boot against |
| every table in the live database exists in the restore | catches a table added by a recent migration that this dump predates |

Head is resolved in this order: `EXPECT_HEAD` env → `alembic heads` inside `BACKEND_CONTAINER`
(default `provekit-backend-1`) → the live database's own `alembic_version`. Set `EXPECT_HEAD`
explicitly if you want the strictest form.

Other env: `MIN_ROWS`, `MIN_BYTES`, `KEEP=1` (leave the drill database behind to poke at a
failure), `DUMP=/path/to.sql.gz` (drill a specific file).

Exit codes: `0` pass, `1` one or more assertions failed, `2` the drill couldn't run at all
(no dump, unreadable gzip, restore rejected). The verdict is also written to
`$BACKUP_DIR/last-drill.txt`.

> **Alert on the age of `last-drill.txt`, not on the drill's output.** A cron job that stops
> running emits no failure — no mail, no log line, nothing. The only signal is a status file
> that quietly stops being updated.

### restore.sh — actual recovery

```bash
bash deploy/restore.sh                                     # newest dump into a NEW database
bash deploy/restore.sh --into provekit_scratch             # named target
bash deploy/restore.sh /path/dump.sql.gz --into provekit --force   # real recovery
```

Two rules it exists to enforce:

1. **It never writes into a database that already has tables without `--force`.** A plain
   `pg_dump` contains no `DROP` statements, so restoring over live data *merges*: duplicate-key
   errors on some tables, stale rows left behind on others. That is worse than no restore, and
   in a log it looks like success.
2. **`--single-transaction` with `ON_ERROR_STOP=1`.** Either the whole database is back or
   nothing changed. There is no half-restored state to reason about at 3am.

With `--force` it terminates other connections to the target and drops it before recreating.
Stop the backend first anyway (`docker compose -f compose.prod.yml stop backend`) — the
connection kill is the seatbelt for when you can't, not the plan.

---

## Recovery procedure

Total data loss / restoring onto a rebuilt host.

```bash
# 1. Stop the app so nothing writes while you work. Leave Postgres up.
cd /root/ProveKit
docker compose -f compose.prod.yml stop backend frontend

# 2. Prove the dump you are about to trust, on the side, before touching the live database.
BACKUP_DIR=/root/provekit-backups bash deploy/verify-restore.sh

# 3. Restore for real. This DROPS the existing database.
bash deploy/restore.sh /root/provekit-backups/provekit-YYYYMMDD-HHMMSS.sql.gz \
     --into provekit --force

# 4. Bring the app back. Alembic runs on startup; if the dump predates a migration,
#    this is where it catches up.
docker compose -f compose.prod.yml start backend frontend

# 5. Verify through the product, not the database.
curl -fsS https://$DOMAIN/healthz     # {"ok":true,"checks":{"db":true,...}}
```

Step 2 is not optional theatre. It is the only step that distinguishes "we have backups" from
"we can come back", and it costs about two seconds per hundred megabytes.

**On a fresh host**, do steps 1–5 after `docker compose -f compose.prod.yml up -d db` and copy
the dump across first. You also need `SECRET_KEY` back: losing it doesn't lose stored data, but
it logs everyone out and invalidates sealed provider credentials, so users must re-enter
provider API keys. Back `SECRET_KEY` up separately from the database — a backup that includes
the key that decrypts it is one theft, not two.

**What the dump does not contain:** the ingest spool (in-flight batches, seconds of data at
most), Redis (rate-limit windows and spend counters — they rebuild), Caddy's certificates (it
re-issues), and your `.env`. Back up the `.env` yourself.

---

## RPO / RTO with the shipped schedule

The installed cron is **daily at 03:15**, retention **7 days**, drill **Sundays at 03:40**.

| | Value | Where it comes from |
|---|---|---|
| **RPO** (data you lose) | **up to 24 hours** | one dump per day; a failure at 03:14 loses everything since the previous 03:15 |
| **RTO** (time to be back) | **minutes**, dominated by dump size | `gunzip \| psql` of a single-file dump, plus app restart |
| **Recovery window** | **7 days** | `RETAIN_DAYS=7`; a corruption you notice on day 8 has no clean copy left |
| **Detection lag on a broken backup** | **up to 7 days** | the drill runs weekly |

Be honest about what those numbers mean before accepting them:

- **24h RPO is a real 24 hours of traces gone**, not a rounding error. If that is unacceptable,
  a daily `pg_dump` is the wrong tool — you want WAL archiving / PITR (`archive_command`, or a
  managed Postgres with continuous backup), which gets RPO to minutes. This repo does not ship
  that; adding it is a Postgres configuration exercise, not a ProveKit one.
- **Cheaper improvements first:** run `backup.sh` every 6 hours (`15 */6 * * *`) to cut RPO to
  6h at 4× the storage, and raise `RETAIN_DAYS`. Both are one-line changes.
- **Run the drill more often than you think you need to.** Daily costs a few seconds and cuts
  the window in which a silently-broken backup can go unnoticed from a week to a day.
- **`RETAIN_DAYS=7` bounds the corruption you can survive, not just the disk you use.** Data
  quietly mangled by a bad deploy and noticed two weeks later is unrecoverable at 7 days.

### The dumps are on the same disk as the database

`BACKUP_DIR` defaults to `/root/provekit-backups` — the same machine, usually the same disk, as
the Postgres volume. That survives `DROP TABLE`, a bad migration, and application bugs. It does
**not** survive the host dying, the volume being deleted, or the provider closing the account,
which are the scenarios people actually mean by "backup".

Ship them off-box. Anything works; the drill doesn't care where the file came from:

```bash
# after backup.sh, in the same cron line
rclone copy /root/provekit-backups remote:provekit-backups --max-age 25h
```

Then periodically run the drill against a dump **pulled back down from the remote**
(`DUMP=/tmp/from-remote.sql.gz bash deploy/verify-restore.sh`) — that is the only way to learn
that your upload has been writing zero-byte files.

---

## What has actually been verified

The scripts in this repo were exercised end to end against a real Postgres 17 container with a
ProveKit schema at head and 25 ingested runs: `backup.sh` produced a dump, `verify-restore.sh`
restored it into a throwaway database and passed all assertions, `restore.sh --force` recovered
the live database after its `runs` table was deliberately emptied, and the ProveKit application
then booted against the restored database and served all 25 runs over `/api/runs`. The failure
paths were exercised too: truncated dump, empty-database dump, wrong `EXPECT_HEAD`, stale
backup, and the refusal to clobber a populated database without `--force` — each fails with a
non-zero exit.

Not verified here: cron scheduling on a live VPS, and any off-box replication (you must set that
up yourself, and drill from the remote copy).
