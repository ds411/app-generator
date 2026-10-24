# 0013. Production settings of the FastAPI app

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

The FastAPI app had a Dockerfile and a Compose file for local runs, but
no structured logs, no rate limits, and no deployment files. A
production platform reads the logs as JSON, and needs probes, resource
limits, and a step that runs the migrations.

## Decision

- Logs: the app writes JSON lines with the standard `logging` package
  and a small formatter, and no new package. A middleware logs each
  request with a request ID (`X-Request-ID`). The server does not write
  its own access log.
- Rate limits: a middleware counts the requests of each client address
  in fixed windows of one minute, in the memory of the process, and
  gives 429 with problem details and `Retry-After`. The setting
  `RATE_LIMIT_PER_MINUTE` is 0 (no limit) by default, so local runs and
  tests do not change.
- Deployment: one target, Kubernetes with Kustomize. The files are plain
  YAML with no templates of their own, and work with each cluster that
  has a container registry. The database is a managed service outside
  the cluster.

### Update for M18: a rate limit for all replicas

With `x-fastapi-rate-limit-store: redis` in the `app` section, the app
can count the requests in Redis (#277):

- The setting `RATE_LIMIT_STORE_URL` selects Redis. Without it, the app
  counts in memory as before. All processes use windows that start at
  the full minutes of the clock, and one transaction (`INCR` and
  `EXPIRE`) counts each request, so all replicas share one limit.
- When Redis is not available, the request passes and the app logs a
  warning, at most once in each window (fail open). With
  `RATE_LIMIT_FAIL_CLOSED=true`, the request gets 503 with problem
  details. A short timeout (one second) keeps a slow Redis from
  stopping the API.
- The Compose file has a `redis` service in the profile `redis`, and
  the Kubernetes files have the two settings. The Redis server itself
  is a managed service outside the cluster, like the database.
- Without the key, the generated app does not change, and has no Redis
  package.
- The check script starts Redis and two processes of the app, and
  checks that they share the limit, and the two behaviours without
  Redis.

## Consequences

- The logs are ready for a log platform without a change.
- The limit of each replica is separate. A limit for all replicas needs
  a shared store (for example Redis) or a limit in the gateway.
  (M18 adds Redis as an option: see the update.)
- Other targets (for example a serverless container service) need their
  own files. The Dockerfile works for all of them.
