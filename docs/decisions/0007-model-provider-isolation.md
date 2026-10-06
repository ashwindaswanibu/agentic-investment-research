# ADR 0007: Keep model inference behind the application tool boundary

Date: 2026-10-05. Status: retain existing providers; Codex integration not qualified.

## Purpose

Run a genuine research pilot without giving the model access to private evaluation
answers, unrelated host files or tools outside ResearchDesk's recorded registry.
The configured API adapter and Claude CLI adapter already define this boundary.
The local application currently has no configured model provider.

## Feasibility evidence

The installed Codex CLI reports version `0.160.0` and an authenticated ChatGPT
session. Only version, help, feature metadata, authentication status and generated
protocol schemas were inspected. No model inference, credential extraction,
configuration change or new Codex chat was performed.

The generated protocol supports `environments: []` to disable environment access.
That description does not establish that every inherited tool, plugin, hook,
memory or instruction source is removed. In particular, the installed response
schema describes `disabledPluginIds` as not yet filtering plugin capabilities.
Its legacy `readOnly` sandbox has only `type` and `networkAccess`; the newer
restricted-read-root recipe in current documentation is not represented there.

Reproduce the version-specific schema inspection with:

```sh
codex --version
codex login status
codex app-server generate-json-schema --experimental --out /tmp/researchdesk-codex-schema
```

Inspect `v2/ThreadStartParams.json`, `v2/TurnStartParams.json` and
`v2/ThreadStartResponse.json`. Authentication status is not proof of live model
access or application isolation. An empty working directory alone is insufficient.

## Decision and reopening condition

Do not introduce a nominally isolated Codex provider based on these observations.
Do not extract or copy its credentials into the API adapter. Keep the two existing
provider paths and their explicit configuration requirement.

Reopen a bounded integration spike when the installed version has a supported,
verifiable tool/context restriction contract. Qualification must show that only
the declared ResearchDesk tools are available before inference, private answer
sentinels remain inaccessible, and cancellation, structured output, bounded usage
and failure recording work through actual provider calls. This is a local
integration decision, not a claim about Codex's general suitability or security.

Official references inspected: [app-server](https://learn.chatgpt.com/docs/app-server),
[configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
[managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration),
and [advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced).
Online documentation and an installed schema can describe different versions;
the latter governs the proposed local integration until verified otherwise.
