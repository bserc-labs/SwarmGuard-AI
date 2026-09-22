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
