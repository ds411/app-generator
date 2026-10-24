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

## Consequences

- The logs are ready for a log platform without a change.
- The limit of each replica is separate. A limit for all replicas needs
  a shared store (for example Redis) or a limit in the gateway.
- Other targets (for example a serverless container service) need their
  own files. The Dockerfile works for all of them.
