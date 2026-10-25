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

### Update for M18: a serverless container service

The key `x-fastapi-deploy` of the `app` section selects the deployment
targets: `kubernetes` (the default, as before), `knative`, or a list of
both (#278).

- `knative`: `deploy/knative/service.yaml` is a Knative Service with the
  probes, the resource limits, the scale (0 to 10 instances), and the
  environment of the app. It uses only the fields that Knative and
  Google Cloud Run share, so Cloud Run accepts the same file (`gcloud
  run services replace`). Thus it has no `envFrom` and no
  `securityContext`: the settings are `env` values, and each secret
  (the database, the sign-in, Redis, and the keys of the third-party
  APIs) is a `secretKeyRef` with the key `latest`, which is a
  Kubernetes Secret in Knative and a Secret Manager version in Cloud
  Run.
- The migrations run before the deployment: a Kubernetes Job
  (`deploy/knative/migrate-job.yaml`) on a cluster with Knative, and a
  Cloud Run job (`gcloud run jobs deploy --execute-now --wait`) on Cloud
  Run. The README of the app gives the commands of each target.
- `/health` checks the database, so the startup probe keeps a new
  instance without the database from getting requests. Cloud Run has no
  TCP liveness probe, so the liveness probe uses `/health` too, with a
  long period.
- The FastAPI check validates the files of each target against their
  JSON schemas without a cluster: the Kubernetes API (strict), the
  Knative CRD, and the Kustomization. It also checks that both targets
  set the same settings of the app. With gcloud installed, it converts
  the Knative Service to the messages of the Cloud Run API, as `gcloud
  run services replace` does.

### Update for M27: the Next.js app

The Next.js app gets the same rate limit, a health route, and the same
deployment targets (#342, #343):

- `proxy.ts` (the middleware of Next.js 16, on Node.js) counts each
  request before the pages, the server actions, and the route handlers.
  The static files of the build are not counted, and `/health` has no
  limit. The settings and the behaviour are the settings of the FastAPI
  app: `RATE_LIMIT_PER_MINUTE`, and with `x-nextjs-rate-limit-store:
  redis` `RATE_LIMIT_STORE_URL` and `RATE_LIMIT_FAIL_CLOSED`. The client
  of Redis is `@redis/client`, with a timeout of one second and no queue
  while it connects again. A 429 or a 503 is a short text in the
  language of the request, because the browser shows it as a page.
- A page view of the Next.js app makes 10 to 25 requests: the page, the
  prefetches of its links, and the server actions that load the data of
  its views. Thus the deployment files set 1200 requests in each minute,
  not 600 as for the FastAPI app, and Compose sets no limit, because the
  UI tests make more requests than a user.
- The proxy of Next.js does not get the address of the connection.
  Next.js sets `X-Forwarded-For` to that address only when the request
  has no such header, so a client without a proxy in front of the app
  can send any address. Thus the app counts by the address that the
  trusted proxies add to the end of the header, and the setting
  `RATE_LIMIT_TRUSTED_HOPS` (default 1, for an ingress or Cloud Run) is
  the number of these addresses: 2 for a load balancer of Google Cloud,
  which adds the address of the client and its own address. The README
  tells the developer to let clients reach the app only through the
  proxy.
- `/health` runs `select 1` on the database, and gives 503 without it.
- `x-nextjs-deploy` gives the targets `kubernetes` (the default) and
  `knative`, with the same files as the FastAPI app. The names start
  with `<app>-web`, so that both apps of a definition can share a
  namespace. The server listens on `HOSTNAME`, which Kubernetes sets to
  the name of the pod, so the files set it to `0.0.0.0`. The Deployment
  has a read-only file system with an `emptyDir` for `.next/cache`.
- The migration Job runs `node migrate.mjs`. The standalone server has
  only the packages that the server bundles need, so the Dockerfile
  bundles `src/shared/db/run-migrate.ts` (Drizzle and `postgres`) with
  esbuild, which `tsx` already installs. `DATABASE_MIGRATE=true` at the
  start of the server stays for Compose and local runs: with more than
  one replica, the Job applies the migrations once.
- `scripts/check-nextjs.sh` runs the checks of the FastAPI app for the
  Next.js app: two processes share the limit in Redis
  (`scripts/check_shared_rate_limit.py nextjs`), and the files of both
  targets match their schemas (`scripts/check_deploy_files.py nextjs`).

## Consequences

- The logs are ready for a log platform without a change.
- The limit of each replica is separate. A limit for all replicas needs
  a shared store (for example Redis) or a limit in the gateway.
  (M18 adds Redis as an option: see the update.)
- Other targets (for example a serverless container service) need their
  own files. The Dockerfile works for all of them. (M18 adds Knative and
  Cloud Run: see the update.)
- The two apps get the client address in different ways. The image of
  the FastAPI app trusts `X-Forwarded-For` from all addresses
  (`--forwarded-allow-ips *`), and uvicorn then uses the first address,
  which the client can set. The Next.js app uses the addresses that the
  trusted proxies add. A later change can give the FastAPI app the same
  rule.
