# Operations guide

How to run SwarmGuard AI on a server: start-up order, secrets, rotation. Each
procedure here was executed against a running stack before it was written down.

## Start-up order

```
postgres ─healthy─▶ migrate ─exit 0─▶ backend ─healthy─▶ frontend (nginx)
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
