# ADR 0009 — host the existing read-only demonstration

Date: 2026-10-05. Status: implemented; constrained container qualification passed;
hosting account access and actual HTTPS deployment pending.

## Job and stopping condition

A reviewer should open an HTTPS link and inspect the same two synthetic workflows
that the local viewer serves. Preserve the Python API, Next interface, provenance
and explicit limitations. Stop after one deployable container, bounded failure
checks and a verified public URL. This does not qualify the agent research loop,
trading operation, provider integrations or a production service.

## Alternatives and decision

Render Free supports a Docker web service, managed HTTPS and an ephemeral file
system. A database generated into the image needs no persistent disk. Its 512 MB,
0.1 CPU instance is the initial qualification target. Free services sleep after
15 idle minutes; a cold start can take about a minute. This is acceptable for a
clearly described demonstration, not continuous research operation.

Sites hosting expects Cloudflare Workers-compatible server output; porting the
Python application would add a second implementation to maintain. Hugging Face
Docker Spaces support the runtime, but the current creation documentation requires
a PRO account. Choose Render for the first deployment, conditional on account
access and a confirmed free configuration. No hosting account is assumed.

One container runs the API on loopback and Next on the host's PORT. A small
supervisor starts Next only after the verified API is ready, shuts both down if
either exits and handles termination with a finite grace period. Only PORT is
accepted from the host; provider settings and upstream overrides are not inherited.
The API retains native read-only SQLite enforcement and explicit disabled providers.
Files are owned by root; the service runs as an unprivileged user. No operator data,
model account, worker, Docker socket or market credential enters the image.

Use locked application dependencies and pinned official Python/Node images on the
same Debian release. Build static frontend assets and the synthetic package into
the image. Do not generate or copy files on startup. Automatic deployment is off
until changes have passed qualification and the operator deliberately deploys them.

## Acceptance evidence

- Build the actual combined image in remote CI; this laptop has about 1 GB free.
- Run at 512 MB with swap disabled beyond that allowance and a 0.1 CPU quota.
  Record cold startup, peak memory and OOM counters. A finite smoke is not a load test.
- Serve both walkthroughs, their case APIs, library search and JS/CSS assets through
  Next. Inspect the real demo in a browser after deployment.
- Verify API mutations and native database writes fail, and the database hash stays
  unchanged. Run with a read-only root, bounded temporary storage and no capabilities.
- Exercise malformed-package startup, loss of a child and graceful shutdown.
- Check the actual hosting workspace's billing configuration before launch. A free
  instance alone does not prevent bandwidth/build overages when a card is on file.
  Do not add a payment method, select paid compute or buy a subscription.

## Primary references

Read 2026-10-05:

- [Render free service limits](https://render.com/docs/free).
- [Render Docker deployment](https://render.com/docs/docker) and
  [web service port contract](https://render.com/docs/web-services).
- [Blueprint schema](https://render.com/docs/blueprint-spec): explicit free plan,
  health path, Dockerfile and disabled automatic deployment.
- [Hugging Face Space creation](https://huggingface.co/docs/huggingface_hub/main/guides/manage-spaces).
- Official [Node bookworm image source](https://github.com/nodejs/docker-node/blob/main/24/bookworm-slim/Dockerfile)
  and [Python bookworm image source](https://github.com/docker-library/python/blob/master/3.12/slim-bookworm/Dockerfile).

Qualification results belong in the verification record. Do not treat this decision
or a deployment manifest as evidence that hosting is live.
The [completed container check](../verification.md#combined-demo-container-2026-10-05)
passed at 180.02 MiB peak memory and 50.72 seconds to first readiness under the
declared limits, including failure and shutdown checks. This supports the selected
free-tier trial; it is not an operating-service qualification.
