# Deploy

ada runs on one Verda VM that it shares with another project, "Tell me when". Pushes to
`main` deploy through `.github/workflows/ci.yml`; nothing is built on the VM.

## What runs where

- **GitHub Actions** builds the three images (`ghcr.io/benni-tec/ada/{backend,frontend,gateway}`),
  tagged `sha-<first 7 of the commit>`, then its `deploy` job opens one SSH connection to the VM.
- **The VM** keeps ada in `/opt/ada`: `docker-compose.yml`, `docker-compose.infra.yml` and
  `docker-compose.deploy.yml` (CI replaces these three), plus `REVISION`, the deployed sha,
  and `RUN`, the highest workflow run number deployed so far.
  The deploy runs `docker compose -f docker-compose.yml -f docker-compose.deploy.yml` at
  `VERSION=sha-<sha>`.
- **Caddy**, owned by the other project, holds ports 80 and 443 and proxies
  `https://ada.95-133-254-42.sslip.io` to `ada-gateway:80` over the external Docker network
  `edge`. ada publishes no host ports: the override removes the PostgreSQL, Valkey and gateway
  ones, because Docker bypasses the host firewall.
  For the Junction event this route has no authentication: anyone with the URL can use the API
  and the MCP endpoint, and with them the paid web and model keys. After the event, remove the
  route or put it behind access control.

`edge` belongs to the front door: its Caddy must be up (so the network exists) before ada
starts, or `up` fails with "network edge not found".

## Repository secrets

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | The VM's address (`95.133.254.42`). A recreated VM changes this and the URL in the workflow's health check. |
| `DEPLOY_SSH_KEY` | Private key of a user on the VM that may run Docker (the controller's `~/.ssh/ada_deploy`). |
| `DEPLOY_KNOWN_HOSTS` | The VM's host key line (the controller's `~/.ssh/ada_known_hosts`); the connection fails on a mismatch. |
| `DEPLOY_USER` | Optional, default `root`. |

While `DEPLOY_HOST`, `DEPLOY_SSH_KEY` or `DEPLOY_KNOWN_HOSTS` is unset, the deploy job skips itself
with a notice.

## Files placed by hand on the VM

CI never writes these two in `/opt/ada`:

- `.env`: `POSTGRES_PASSWORD=...`. The deploy sets `VERSION` itself.
- `.env.local`: `ADA_SECRET_KEY=...`, the master key of the stored agent API keys (see the README).
  Keep it: keys stored under a lost key cannot be read.

## Order of deploys

Deploys run one at a time; later ones wait in line rather than replace one another, and on the VM
they also take a lock. A push deploy skips itself when `RUN` is a later run, so an older push never
replaces a newer push or a rollback started after it. That includes re-running an earlier push's
workflow run: roll back with a manual run instead. Renaming the workflow file starts its run numbers
again at 1; delete `RUN` on the VM then.

## Rolling back

Run the CI workflow by hand from main (Actions, CI, Run workflow; other branches never deploy) with `ref` set to an earlier commit
whose images exist and which has `docker-compose.deploy.yml` (this deploy's first commit or later;
older commits were never deployed this way). It deploys that commit's `sha-<short>` images; the compose files come from
that commit too. The deploy then checks `https://ada.95-133-254-42.sslip.io/api/health/live`
for up to three minutes.
