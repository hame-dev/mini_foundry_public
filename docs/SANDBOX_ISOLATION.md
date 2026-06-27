# Sandbox Isolation (Docker socket trust boundary)

User code (notebook cells, `@transform` code, repo tests) never runs in the
backend or worker process — it runs in a locked-down container spawned by
`app/notebooks/sandbox.py` with: `--network=none --read-only --cap-drop=ALL
--user=65534 --no-new-privileges --pids-limit=128 --memory=1g --cpus=1` and a
per-run, size-quota'd workspace.

## The remaining risk

To *spawn* those containers the Celery worker needs to reach a Docker daemon.
The default `docker-compose.yml` mounts the **host** socket
(`/var/run/docker.sock`) into the worker. That socket is root-equivalent: a
worker compromise becomes host compromise. The sandbox containers themselves do
**not** get the socket, but the worker does.

## The fix: isolate the daemon

The sandbox now talks to a configurable daemon instead of assuming the host
socket. Two settings (env-overridable) control this — see `app/config.py`:

| Setting | Env var | Effect |
|---|---|---|
| `sandbox_docker_host` | `SANDBOX_DOCKER_HOST` | Sets `DOCKER_HOST` for every `docker` call the worker makes. Point it at a dedicated/rootless/remote daemon, e.g. `tcp://docker-rootless:2375` or `unix:///run/user/1000/docker.sock`. Empty = inherit (host socket). |
| `sandbox_runtime` | `SANDBOX_RUNTIME` | Adds `--runtime=<value>` to `docker run`, e.g. `runsc` (gVisor) or `kata-runtime` (Kata Containers). Empty = daemon default. |

When `SANDBOX_DOCKER_HOST` is set, the worker no longer needs the host socket
mount at all.

## Reference deployment (rootless dind)

`docker-compose.hardened.yml` adds a rootless `docker:dind-rootless` side
daemon and points the worker at it. One base edit is still required because
Compose cannot *unmount* a volume via an overlay:

1. Delete the line `- /var/run/docker.sock:/var/run/docker.sock` from the
   `worker` service in `docker-compose.yml`.
2. `docker compose -f docker-compose.yml -f docker-compose.hardened.yml up`

Confirm the worker has no host socket:

```
docker compose -f docker-compose.yml -f docker-compose.hardened.yml config \
  | sed -n '/  worker:/,/^  [a-z]/p' | grep docker.sock   # -> no output
```

## Production options (stronger, infra-level)

The configurable code path supports these without further code changes:

- **gVisor** — install `runsc` on the sandbox daemon, set `SANDBOX_RUNTIME=runsc`.
- **Kata Containers** — set `SANDBOX_RUNTIME=kata-runtime`.
- **Kubernetes Jobs** with a restricted `RuntimeClass` — run the worker as a job
  dispatcher targeting a node pool with gVisor/Kata; never mount the node socket.
- **Firecracker microVMs** / isolated compute nodes for the sandbox daemon.

`config.production_hardening_issues()` requires `rootless_sandbox_host=true` (and
a digest-pinned `sandbox_image`) before a `production` deployment will boot.
