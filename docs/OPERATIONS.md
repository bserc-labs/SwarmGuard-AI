# Operations guide

How to run SwarmGuard AI on a server: start-up order, TLS, secrets, rotation. Each
procedure here was executed against a running stack before it was written down.

## Start-up order

```
postgres ─healthy─▶ migrate ─exit 0─▶ backend ─healthy─▶ frontend (nginx, :443)
redis ────healthy───────────────────▶
```

- **`migrate`** is a one-shot job: `alembic upgrade head`, then the optional first
  admin, then it exits. It is the same image and tag as the API.
- **`backend`** starts only if `migrate` exited 0. It never migrates. At start it
  checks the database is at the revision the build ships:

  | Database is… | API does | Why |
  |---|---|---|
  | at head | serves | |
  | behind, or never migrated | **refuses to start**, exit 3, names the fix | new code on an old schema otherwise fails later, on some request, as a 500 |
  | ahead (a revision this build has never seen) | warns and serves | that is what a **rollback** looks like; refusing would make every rollback an outage |

- Two migrators that overlap are safe: Alembic holds a PostgreSQL advisory lock
  for the length of a run, so the second waits and then finds nothing to do.

Useful commands:

```bash
docker compose run --rm migrate                 # migrate by hand
docker compose run --rm backend alembic current # what revision is the database at?
docker compose logs migrate                     # why did the API not start?
```

**The rule that makes rollbacks safe.** Rolling an image back does not roll the
schema back. So a migration must stay compatible with the *previous* release:
add columns as nullable or with a default, and remove a column only in the
release *after* the code stopped using it (expand, then contract).

## Health and readiness

Two questions, two endpoints, on purpose:

| Endpoint | Question | Touches | Used by |
|---|---|---|---|
| `GET /health` | Is the process up? | nothing | a liveness probe: restart on failure |
| `GET /ready` | Can it do useful work right now? | postgres (`SELECT 1`), redis (`PING`), each with a 3 s deadline | the compose health check, the deploy smoke test, a load balancer or orchestrator readiness probe |

`/ready` answers **503** with the failing check named when a required dependency
is down, 200 otherwise. It needs no token: an orchestrator asks it every few
seconds. Through nginx it is `/api/ready`.

```json
{"status": "not_ready", "checks": {"database": {"ok": false, "required": true, "detail": "postgres unreachable: OperationalError"}, "redis": {"ok": true, "required": true, "detail": "redis"}}}
```

Why the split matters: Docker restarts a container whose *health check* fails.
Point that at a probe which also fails when the database is down, and a
database outage becomes a restart storm on every API replica. So the compose
health check uses `/ready` (it marks the container unhealthy, which
`depends_on` and `docker ps` see, and does **not** restart it), while a
Kubernetes-style setup should use `/health` for liveness and `/ready` for
readiness.

**Redis is a judgement call.** Without it, live alerts do not reach an
operator's screen and the login rate limiter falls back to per-process memory,
so by default a Redis outage makes the instance not ready
(`READINESS_REQUIRES_REDIS=true`). With several replicas behind a load balancer
that turns a partial outage into a total one; set it `false` there and the
check is reported as a warning instead.

Measured on the development stack, postgres stopped under an already-healthy
container (compose probes every 10 s, three failures make it unhealthy):

| Moment | `/health` | `/ready` | container |
|---|---|---|---|
| postgres stopped, +5 s | 200 | **503** `postgres unreachable` | healthy |
| +30 s | 200 | 503 | **unhealthy** |
| postgres started, +5 s | 200 | 200 | unhealthy |
| +10 s | 200 | 200 | healthy |

The backend's restart count stayed at 0 throughout: the outage was visible
without becoming a restart loop.

### Background loops

Two loops run inside the API: the **heartbeat monitor** (every 10 s; it is what
detects a jammed, silent drone) and **telemetry retention** (hourly). Both run
under a supervisor that restarts a loop with backoff when its pass raises,
brings the task back if it ever ends for any other reason, and records the time
of each successful pass. `/ready` reports them:

```json
"background": {"heartbeat-monitor": {"interval_s": 10.0, "ticks": 42, "failures": 0, "restarts": 0, "seconds_since_tick": 3.1, "stalled": false, "last_error": null, "alive": true}, ...}
```

A loop that has not ticked for three intervals plus 30 s is **stalled**, and a
stalled loop makes `/ready` answer 503 (`checks.background`). For the heartbeat
monitor that is the difference between "no drone is jammed" and "nobody is
looking", which used to be indistinguishable: it ran as a bare task, and a task
that dies is simply gone.

## Releases and deploys

CI publishes images; a script on the host deploys them; a failed deploy rolls
itself back.

### What CI publishes

On every push to `main`, once every other job is green, the `release` job
builds both images, scans them with Trivy, and pushes them to the GitHub
container registry:

```
ghcr.io/bserc-labs/swarmguard-backend:sha-<full commit sha>
ghcr.io/bserc-labs/swarmguard-frontend:sha-<full commit sha>
```

The `sha-` tag is **immutable**: it names exactly one commit, so "what is
running" is never in doubt and a rollback is the previous tag. `main` and
`latest` are pushed too, for looking around; `deploy.sh` refuses them.

The scan is the gate: a CRITICAL or HIGH finding with a fix available means
nothing is published from that commit. It scans the built image, so it sees the
base layers and the virtualenv, which the filesystem scan in the other job
cannot. The first run of it found two HIGH findings, both in copies of
`msgpack` and `setuptools` that pip vendors for its own use; the runtime image
no longer ships pip at all.

### Deploying

```bash
scripts/deploy.sh sha-<commit>     # the release job prints this in its summary
scripts/deploy.sh --status         # what is running, and what was before it
scripts/deploy.sh --rollback       # go back one release
```

`deploy.sh` runs on the host next to `docker-compose.yml`, using
`docker-compose.prod.yml` to replace every `build:` with the published image.
In order it:

1. pulls the three images for the tag, so a tag that does not exist fails
   before anything running is touched;
2. brings the stack up with `--no-build`: the `migrate` job runs, the API starts
   only if it succeeded, nginx last;
3. smoke-tests `http://localhost/healthz` and `https://localhost/api/ready`
   for up to two minutes (`SWARMGUARD_SMOKE_TIMEOUT_S`) — readiness, so a
   release whose API comes up but cannot reach its database is a failed deploy;
4. on success records the tag; on failure redeploys the previous tag,
   smoke-tests that, prints each service's status and log tail, and **exits 1
   either way** — a deploy that failed is never reported as anything else, even
   after a rollback that worked.

Measured on the development host against a throwaway registry: a good tag
deploys and passes; a release whose frontend image was not nginx failed its
smoke test, was rolled back, the site answered 200 afterwards, and the bad tag
was never recorded as current.

For a self-signed development certificate set `SWARMGUARD_SMOKE_INSECURE=1`;
leave it unset on a server. To deploy from a different registry set
`SWARMGUARD_IMAGE_PREFIX`.

**Rollback and the schema.** Rolling an image back does not roll the schema
back. The previous release then starts against a newer schema, sees a revision
it does not know, warns, and serves. That is safe only because of the rule in
*Start-up order* above: a migration must stay compatible with the previous
release for one release.

**Not yet:** there is no server to deploy *to*, so the last hop is this script
run on the host rather than a job that runs it. When there is one, the natural
next step is a `deploy` workflow with an environment approval that runs
`deploy.sh` over SSH.

## TLS

nginx serves the application on **443** only. Port 80 answers a health probe
(`/healthz`), the Let's Encrypt challenge path, and redirects everything else —
including `/api` — so nothing is ever served in clear text. TLS 1.2 and 1.3
only; HSTS for one year.

The certificate is **mounted, never baked into the image**: put `tls.crt` (the
full chain) and `tls.key` in `./certs/`, or point `SWARMGUARD_CERTS_DIR` at them.

| `./certs` contains | nginx does |
|---|---|
| `tls.crt` and `tls.key` | uses them (linked, not copied) |
| nothing | generates a **self-signed** certificate at start and warns loudly — fine on a laptop, never on a server |
| only one of the two, or an empty file | **refuses to start** with a clear error |

The last row is deliberate. Falling back to self-signed when half a pair is
installed would bring the site up looking fine while everyone believes the real
certificate is in use.

The key must be readable by the unprivileged nginx user, whose uid does not
exist on the host: `chmod 700 certs && chmod 444 certs/tls.key`, the same
arrangement as `./secrets`.

**Local development.** `scripts/make-dev-cert.sh` writes a self-signed pair to
`./certs` so the certificate is stable across container recreations and the
browser warning only has to be accepted once.

**Let's Encrypt.** Needs a public DNS name pointing at the host and port 80
reachable from the internet:

```bash
certbot certonly --webroot -w ./acme -d swarmguard.example.org
cp /etc/letsencrypt/live/swarmguard.example.org/fullchain.pem certs/tls.crt
cp /etc/letsencrypt/live/swarmguard.example.org/privkey.pem   certs/tls.key
chmod 444 certs/tls.crt certs/tls.key
docker compose exec frontend nginx -s reload     # no restart, no dropped sockets
```

Put the last three lines in certbot's `--deploy-hook` so renewals apply
themselves. Verified here: a file written under `./acme/.well-known/acme-challenge/`
is served over plain HTTP with a 200 while every other path is redirected. Not
verified here: issuance against the real CA, which needs a domain this project
does not have yet.

Check a deployment from outside:

```bash
curl -sI http://HOST/ | head -1                                  # 301
curl -sI https://HOST/ | grep -i strict-transport-security        # present
openssl s_client -connect HOST:443 -tls1_1 </dev/null 2>&1 | grep -c "alert"   # refused
```

## Backups and restore

The `backup` service takes a compressed `pg_dump` every 6 hours and keeps 14
days of them on the `backups` volume. It is the same image as postgres, so
`pg_dump` and the server are always the same version.

| Commitment | Value | Where it comes from |
|---|---|---|
| **RPO** — most data that can be lost | 6 h (`BACKUP_INTERVAL_S`) | the dump interval |
| **RTO** — time to be back | ~1 min at today's size (`restore` measured at 32 s including API stop/start on an 11 MB database); grows with the database | the rehearsal prints the restore time each run |
| Retention | 14 days (`BACKUP_RETAIN_DAYS`) | prune step |

**A backup on the same disk as the database survives a bad migration, not a dead
disk.** Point `SWARMGUARD_BACKUP_DIR` at a directory that is itself copied off
the host (rsync, restic, an object-storage sync). For minute-level RPO use WAL
archiving (WAL-G or pgBackRest) to a bucket; that needs a bucket this project
does not have yet, so it is the next step, not this one.

```bash
docker compose run --rm backup /scripts/check-backups.sh     # recent and complete? exit 1 if not
docker compose run --rm backup /scripts/rehearse-restore.sh  # dump, restore to scratch, compare, drop
docker compose run --rm backup /scripts/backup.sh --once     # a dump right now
docker compose logs backup                                   # what the loop has been doing
```

`pg_dump` prints a warning about circular foreign keys on `continuous_agg`.
That is TimescaleDB's own catalogue and is harmless for a full dump.

### Rehearse the restore

An untested backup is a hypothesis. `rehearse-restore.sh` takes a fresh dump,
restores it into `<db>_rehearsal`, compares every table's row count with the
live database, checks that `telemetry_logs` is still a hypertable with the same
chunks, drops the scratch database, and prints how long the restore took. CI
runs it on every push against the database the live security suite has just
filled. On a busy server, rows arrive between the dump and the compare:
`--allow-drift` reports a table that has *more* rows live than restored instead
of failing on it. Fewer, or a missing table, still fails.

### Restore for real

```bash
docker compose stop backend                       # its connections would be killed mid-request
docker compose run --rm backup /scripts/restore.sh --yes           # newest dump
docker compose run --rm backup /scripts/restore.sh --yes --dump /backups/swarmguard-20260921T180000Z.dump
docker compose start backend
```

`--yes` is required for the live database; without it the script tells you to
try `--into <scratch>` first. Every step stops on error, and `pg_restore` runs
with `--exit-on-error`, because its default is to carry on past errors and exit
0 with a partial database. A failed restore into a scratch database drops it; a
failed restore of the live database keeps it and says **INCOMPLETE** loudly,
since there may be nothing better to replace it with.

Why not plain `pg_restore`: TimescaleDB needs `timescaledb_pre_restore()`
before the data and `timescaledb_post_restore()` after it, in a fresh database
that already has the extension. Without that the catalogue is wrong in ways
that surface at the first chunk operation, not at restore time.

Verified here, on the development stack: a live restore with the API stopped
took 32 s end to end and every table matched afterwards; a truncated dump
failed and was cleaned up; a `.partial` and a live restore without `--yes` were
both refused.

## Resource limits

Every container has a memory, CPU and PID limit, rotates its logs (5 × 10 MB),
runs with `no-new-privileges`, and the three that run unprivileged drop every
capability. Without limits one runaway container takes the host down, and the
database with it; with them, Docker restarts just that container.

| Service | Memory | CPUs | Basis |
|---|---|---|---|
| backend | 1 GiB | 2 | measured 206 MiB idle, 270 MiB with the ML model and SHAP loaded; detections and the 60-connection pool need headroom |
| postgres | 2 GiB | 2 | `shared_buffers` 512 MB and `effective_cache_size` 1.5 GB are passed on the command line and **must move with the limit** (25% / 75%) |
| redis | 256 MiB | 0.5 | `maxmemory 192mb`, `volatile-lru`: evicts expiring rate-limit keys itself rather than being OOM-killed, which would drop every live socket |
| frontend | 128 MiB | 0.5 | nginx |
| migrate | 512 MiB | 1 | one-shot |

**Why postgres needs the command-line settings.** The TimescaleDB image runs
`timescaledb-tune` when it first initialises a volume and sizes postgres to the
memory it can see, which is the *host's*: on an 8 GB machine that was
`shared_buffers = 1984MB`. Put a 2 GB limit on a database configured like that
and it grows into its buffers until the kernel kills it. Settings on the command
line override `postgresql.conf`, so they hold for old volumes and new ones alike.
Every value is overridable from `.env` (`POSTGRES_MEMORY_LIMIT`,
`POSTGRES_SHARED_BUFFERS`, …); raise them together.

Check what is enforced:

```bash
docker inspect swarmguard-backend --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}'
docker compose exec postgres psql -U "$POSTGRES_USER" -c "SHOW shared_buffers"    # 512MB, source: command line
docker stats --no-stream
```

## Secrets

Secrets are files, one per value, in `./secrets/` on the host (gitignored; move it
with `SWARMGUARD_SECRETS_DIR`), mounted read-only at `/run/secrets`.

| File | Setting | Mounted into |
|---|---|---|
| `secret_key` | `SECRET_KEY` — signs login tokens | migrate, backend |
| `secret_key_previous` | `SECRET_KEY_PREVIOUS` — empty except mid-rotation | migrate, backend |
| `drone_api_key` | `DRONE_API_KEY` — shared device key | migrate, backend |
| `postgres_password` | `POSTGRES_PASSWORD_FILE` / `DATABASE_PASSWORD` | postgres, migrate, backend |
| `admin_password` | first admin; empty = do not provision | **migrate only** |

```bash
scripts/init-secrets.sh           # create what is missing; never overwrites
scripts/init-secrets.sh --check   # verify; changes nothing; exit 1 on a problem
```

Why files: an environment variable is printed by `docker inspect`, inherited by
every child process and captured in crash dumps. Compose passes every secret to
the containers as an **empty** variable on purpose. `environment:` beats
`env_file:`, and the application treats empty as unset, so a secret left behind
in `.env` still cannot reach a container. Check it yourself:

```bash
docker inspect swarmguard-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'KEY|PASSWORD'
# SECRET_KEY=          <- empty is correct
```

The directory is `0700` and the files `0444`. That is deliberate: compose
bind-mounts the files and the containers read them as users whose uid does not
exist on the host, so it is the directory that keeps other host users out.

For a real deployment, point `SWARMGUARD_SECRETS_DIR` outside the checkout —
a tmpfs, or the directory your secret manager's agent (Vault Agent, SOPS,
cloud secret CSI) writes to. The application only needs the files to exist.

## Rotating keys

### `SECRET_KEY` (login tokens) — no outage

Tokens already issued were signed with the old key and live for
`ACCESS_TOKEN_EXPIRE_MINUTES` (60 by default). So rotation has two halves:

```bash
scripts/rotate-secret-key.sh                    # old key -> previous, new key generated
docker compose up -d --force-recreate backend
# ... wait at least ACCESS_TOKEN_EXPIRE_MINUTES ...
scripts/rotate-secret-key.sh --finish           # previous key cleared
docker compose up -d --force-recreate backend
```

Measured on a running stack:

| Moment | Session from before | Session from after |
|---|---|---|
| rotation started | 200 — still valid | 200 |
| rotation finished | **401** — old key is dead | 200 |

**If the key has leaked**, do not give it a grace period. Anyone holding it can
mint a valid admin token until it stops verifying:

```bash
scripts/rotate-secret-key.sh --emergency        # everyone signs in again
docker compose up -d --force-recreate backend
```

### Database password

```bash
NEW=$(openssl rand -hex 32)
docker compose exec postgres psql -U "$POSTGRES_USER" -c "ALTER ROLE \"$POSTGRES_USER\" PASSWORD '$NEW'"
rm -f secrets/postgres_password && printf '%s' "$NEW" > secrets/postgres_password && chmod 444 secrets/postgres_password
docker compose up -d --force-recreate backend
```

Change the role first, the file second. `POSTGRES_PASSWORD_FILE` is read by
postgres only when it initialises an empty volume, so editing the file alone
changes nothing in the database and locks the API out.

Measured: in the right order the API reconnects at once. With the file changed
and the role not, the API **does not start** — its start-up schema check cannot
connect — which is a clearer failure than a running API answering 500.

### `DRONE_API_KEY`

One key is shared by the whole fleet, so rotating it means re-keying every
aircraft at the same moment. There is no graceful version of that, which is why
per-device credentials are on the roadmap (`reports/03-PRODUCTION-ROADMAP.md`,
item 3.2). Until then: replace `secrets/drone_api_key`, restart the API, and
update every device.
