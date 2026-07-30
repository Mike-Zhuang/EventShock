<p align="right">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a>
</p>

![EventShock Lab — evidence-bound counterfactual market stress testing](docs/assets/readme/eventshock-banner.svg)

# EventShock Lab

<p align="center">
  <strong>Change one condition. See whether the same shock gets worse—inside a simulation, not as a forecast.</strong>
</p>

<p align="center">
  <a href="https://github.com/Mike-Zhuang/EventShock/actions/workflows/ci.yml"><img alt="CI status" src="https://github.com/Mike-Zhuang/EventShock/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <img alt="Python 3.12.13" src="https://img.shields.io/badge/Python-3.12.13-3776AB?logo=python&logoColor=white">
  <img alt="React and TypeScript" src="https://img.shields.io/badge/React%20%2B%20TypeScript-Production%20UI-0F62FE?logo=react&logoColor=white">
  <a href="LICENSE"><img alt="PolyForm Strict 1.0.0 source-available license" src="https://img.shields.io/badge/License-PolyForm%20Strict%201.0.0-FFB000"></a>
</p>

<p align="center">
  <a href="https://eventshock.mikezhuang.cn"><strong>Live demo</strong></a>
  · <a href="#quick-start">Quick start</a>
  · <a href="#documentation">Documentation</a>
  · <a href="https://github.com/Mike-Zhuang/EventShock/issues/new/choose">Report an issue</a>
</p>

**Change one condition. See whether the same shock gets worse.** EventShock Lab lets market event-risk analysts, institutional research teams, and educators compare two simulated versions of the same event: a baseline and one controlled change. Its primary purpose is institutional event-risk research and teaching—not individual investment decision-making.

> [!IMPORTANT]
> EventShock Lab does not tell anyone whether to buy or sell, when to trade, what target price to expect, what will happen in the real world, or whether an investment will earn a return. Real-world facts in the flagship SpaceX case are separated from explicitly synthetic prices, order books, flows, agent behavior, and counterfactual effects.

Current evidence status is deliberately limited: the historical cases are runnable mechanism studies, not independently calibrated or externally validated forecasting models. Target-user interviews and independent domain review remain planned human evidence; this repository does not claim that they have already been completed.

## What it does

EventShock is designed around one controlled question: **if exactly one declared condition changed, would the same simulated shock become better, worse, or materially different?** The system answers that question only inside its stated model and assumptions.

```text
Select a traceable or fully synthetic Event Pack
  -> approve, edit, or reject candidate claims
  -> freeze the evidence set for this research session
  -> choose rule-only or bounded LLM-assisted cognition
  -> change exactly one counterfactual intervention
  -> run 10, 25, or 50 matched random seeds
  -> compare distributions and paired differences
  -> trace event -> belief -> order -> trade -> outcome
  -> export a reproducibility bundle
```

Prices are produced by an integer-tick, price-time-priority limit order book—not by an LLM. The same configuration and seed can be replayed deterministically, and a matched baseline/intervention pair may differ only in its declared intervention.

## Why EventShock

| Principle | Product behavior |
| --- | --- |
| Evidence before simulation | Candidate claims carry source and timing metadata, require human review, and become immutable when the Event Pack is frozen. |
| Paired by construction | Baseline and intervention runs share matched seeds and, in hybrid mode, the same frozen cognition tape. |
| Deterministic market core | Orders pass through fixed policies, ledgers, risk controls, and a price-time-priority matching engine. |
| Human authority | People approve facts, choose the research question, define the single intervention, and interpret every consequential result. |
| Inspectable uncertainty | Results show distributions, empirical intervals, paired effects, stopping behavior, versions, sources, and limitations. |
| Reproducible artifacts | Exports include JSON, CSV, Markdown, Parquet, hashes, configuration, traces, and replay metadata. |

## Product capabilities

### Evidence and experiment design

- A flagship **SpaceX 2026 IPO and rapid Nasdaq-100 inclusion** Event Pack with traceable official facts, point-in-time boundaries, and clearly separated synthetic market mechanics.
- Runnable **CrowdStrike 2024 outage** and **GameStop 2021 social cascade** historical case packs, explicitly marked as case-ready rather than historically calibrated validation results.
- An owner-isolated Event Pack Factory for multi-source paste ingestion and Zhipu Web Search discovery, followed by server-side Reader retrieval, source-by-source review, and materialization into a draft Event Pack.
- Manual expert controls and a persisted, bounded AI-guided workflow. Onboarding recommends a mode from self-reported experience and assistance preference; it does not test or rank the user, and the user remains free to choose either mode.
- Text and file import, deterministic or model-assisted claim extraction, bilingual editing, rejection, approval, and frozen Event Packs. Search snippets are discovery aids only and can never support claims or freezing.
- Deterministic content-safety screening before extraction or external-model calls; blocked high-risk content is not persisted, and reviewable content requires human confirmation and redaction.
- Seven single-variable interventions: market-maker capacity, social amplification, stop-loss sensitivity, clarification delay, liquidity depth, passive flow, and information delay.
- Scenario create, save, clone, freeze, and diff workflows with typed market, population, network, cognition, metric, and stopping-rule configuration.

### Simulation and market mechanics

- Eleven rule-agent roles covering noise, value, momentum, mean reversion, market making, passive flow, institutional execution, stop-loss, deleveraging, forced liquidation, and arbitrage behavior.
- Limit orders, partial fills, IOC, price protection, self-trade prevention, inventory-aware quoting, borrowing, margin, forced liquidation, and deterministic discrete-event traces.
- Six information-network families with strict `publishedAt`, `knownAt`, `scheduledAt`, and simulation-time separation to prevent future-information leakage.
- A background experiment queue with SSE status, cancellation, durable history, matched-pair checkpoints, retryable recovery, and frozen-cognition reuse after a service restart.

### Results, validation, and reproducibility

- Seventeen risk, liquidity, network, agent-economic, liquidation, and LLM metrics with empirical intervals, paired bootstrap estimates, effect sizes, sign consistency, and tail probabilities.
- Distribution-first result pages, paired-seed differences, market-path diagnostics, mechanism Trace Explorer, executive risk cards, and explicit result invalidation without rewriting the audit chain.
- Sequential stopping rules, negative controls, parameter-recovery knockouts, local two-level sensitivity, exact sign tests, and family-level Holm correction. These are model-internal diagnostics, not proof of real-world causality.
- A Study Workbench with preregistered templates, bounded factorial and Latin-hypercube designs, common seeds, ablations, sensitivity screens, and immutable study history.
- Reproducibility ZIP files containing the manifest, Event Pack, scenario, results, cognition decisions, traces, bilingual reports, CSV tables, and six fixed-schema Parquet tables.

### Accounts and durable research history

- Email registration, bilingual verification mail, sign-in, sign-out, and password reset.
- Research objects are durably owned by the verified account; administrators receive a separate privacy-minimized user and activity overview.
- Each account retains up to 30 experiments, terminal experiments for up to 90 days, and the deployment retains up to 500 experiments globally. Long-lived artifacts should be exported before retention limits apply.
- Completed experiments can be marked `INVALIDATED` with a reason while preserving underlying results and the audit hash chain; invalidated results are rejected by normal result, metric, trace, and export paths.

## Optional AI and BYOK

The default path is deterministic, replayable, and key-free: `RULE_ONLY`.

Users may temporarily configure their own provider key and enable `HYBRID_LLM`. Zhipu AI is the default provider and `glm-5.2` is the default model. Provider-neutral adapters are also available for OpenAI, Anthropic, Google Gemini, DeepSeek, Alibaba Cloud Model Studio/Qwen, and Moonshot/Kimi. Non-Zhipu providers are currently labeled **community preview** because they have automated contract coverage but have not all completed live-provider acceptance testing.

Provider outputs use native JSON Schema or JSON Object modes where available, followed by strict local schema, evidence, and action validation, one bounded repair attempt, and deterministic fallback. When a safe partial fallback occurs, the experiment is labeled `HYBRID_LLM_PARTIAL_RULE_FALLBACK` with item-level reasons. Disabling `fallbackToRules` makes any attempted rule fallback fail closed.

The API key is isolated to the current authenticated session and held only in server-process memory. It is removed on sign-out, expiry, provider switch, or service restart, and is never written to the account, SQLite database, browser persistence, logs, or export bundle.

Users may customize only the provider-supported subset of `temperature`, `topP`, `presencePenalty`, `frequencyPenalty`, `seed`, and `timeoutSeconds`, within server-enforced ranges. Arbitrary base URLs, request headers, tools, system prompts, and free-form provider payloads are intentionally unavailable.

LLMs may propose candidate facts or bounded belief and action preferences. They cannot set prices, bypass risk controls, access undeclared real-time data, or submit orders directly. The deterministic policy, ledger, and matching layers remain authoritative.

The result page also offers an explicit BYOK interpretation assistant. It reads a bounded authoritative result snapshot through allowlisted tools, streams safe progress, validates structured evidence citations, supports bilingual multi-turn follow-up, and stores only validated final conversations under the current account. It does not return private chain-of-thought.

System prompts are source-visible under this repository's source-available license. Runtime protection therefore does not depend on prompt secrecy: untrusted content is delimited as data, model outputs pass deterministic leak and injection checks plus strict schemas and allowlists, and unsafe output fails closed. These controls reduce—not eliminate—prompt-injection risk, so human review remains mandatory.

Provider capabilities, price references, endpoint policy, validation status, and privacy boundaries are documented in the [AI provider guide](usage_documents/ai-providers.md). The ingestion lifecycle is documented separately in the [Event Pack Factory guide](usage_documents/event-pack-factory.md).

## Architecture

```text
Browser
  -> Caddy (public HTTPS, security headers, compression)
  -> BaoTa Nginx (private :18080 reverse proxy and traffic accounting)
  -> EventShock application
       ├─ FastAPI API + built React/TypeScript/Carbon assets
       ├─ SQLite account, Factory, guided-workflow, scenario, experiment, study, audit, and AI-chat state
       ├─ deterministic event queue, information network, ledger, and order book
       ├─ SMTP-over-SSL bilingual verification mail
       └─ allowlisted multi-provider structured-cognition gateways (optional BYOK)
```

Production uses two lightweight containers plus host-managed BaoTa Nginx. Caddy owns public ports 80/443 and TLS; Nginx listens only on the Docker-private path at port 18080; the application additionally binds to host loopback at `127.0.0.1:18000`. SQLite, certificates, and configuration live in persistent volumes.

## Quick start

### Runtime requirements

- **CPython 3.12.13 exactly** for development, tests, containers, and deployment.
- Node.js 22–26 for the frontend; CI uses Node.js 22.
- Conda is the default local environment manager unless you can independently guarantee the same interpreter version, isolation, and dependency consistency.

Do not install project dependencies into system Python, Conda `base`, or another project's environment.

### Create the environment

```bash
conda env create --file environment.yml
conda activate eventshock
python -c "import sys; print(sys.executable); assert sys.version_info[:3] == (3, 12, 13)"
```

If the `eventshock` environment already exists, reuse it after verifying the interpreter version. Do not recreate it blindly.

### Run locally

Terminal 1—start the API:

```bash
conda activate eventshock
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2—start the frontend; Vite proxies `/api` to `127.0.0.1:8000`:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Local development disables email authentication by default and uses isolated `X-Session-ID` research data. Production forces authenticated Secure Cookies and fails closed when required authentication or SMTP secrets are missing.

### Production-style local build

```bash
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

FastAPI serves the tracked `frontend/dist` single-page application after the build completes.

## Replaying an exported experiment

```bash
conda activate eventshock
python scripts/replay-bundle.py /path/to/eventshock-experiment.zip
```

Replay reruns every matched pair under the same code version and CPython 3.12.13, then checks the configuration, Event Pack, event-log, and run-level metric hashes. This verifies deterministic model replay—not external historical validity.

## Tests and quality gates

```bash
conda activate eventshock
python -m ruff check backend tests
python -m ruff format --check backend tests
python -m pytest

cd frontend
npm run typecheck
npm test
npm run build
```

The suite covers matching priority, partial fills, price protection, auctions, volatility halts, point-in-time information isolation, networks, ledgers, content safety, structured cognition, deterministic replay, paired statistics, studies, account isolation, email verification, Cookie/CSRF boundaries, checkpoint recovery, invalidation, SSE, lifecycle behavior, and ZIP/Parquet exports.

## Docker and self-hosted deployment

```bash
cd frontend
npm ci
npm run build
cd ..
cp .env.example .env
docker compose up --detach --build
```

The production server never builds the frontend. `frontend/dist` is a tracked release artifact and must be rebuilt and committed with every frontend source change.

The live deployment follows a GitHub pull model:

```text
codex/* feature branch
  -> local tests and tracked frontend build
  -> Pull Request into main
  -> required GitHub CI checks
  -> BaoTa scheduled task fetches the approved main commit
  -> immutable image build and health checks
  -> atomic release switch, or automatic rollback on failure
```

The BaoTa task runs every ten minutes, records native task logs, rejects non-fast-forward updates, and verifies that the container and public `/api/health` endpoint report the target commit SHA. See the [self-hosted deployment guide](usage_documents/server-deploy.md) for DNS, TLS, firewall, Nginx, rollback, and operations.

## Repository map

```text
backend/                       FastAPI, SQLite, experiment services, simulation core
event-packs/                   traceable and fully synthetic Event Packs
frontend/                      React, TypeScript, Carbon UI, bilingual interface
frontend/dist/                 tracked production frontend artifact
tests/backend/                 simulation, service, security, and API tests
usage_documents/               installation, Git, agent, AI-provider, and server guides
.github/workflows/ci.yml       Python 3.12.13, frontend, and container CI
Dockerfile                     Python 3.12.13 runtime image
compose.yml                    Caddy, application, and persistent volumes
Caddyfile                      automatic HTTPS and reverse proxy
requirements*.lock             reviewed production and development dependency locks
```

## Documentation

- [中文 README](README.zh-CN.md)
- [End-to-end product and research blueprint (Chinese)](EventShock_Lab_End_to_End_Blueprint_ENGIN170E_CN.md)
- [Environment installation guide (Chinese)](usage_documents/install.md)
- [Event Pack Factory and guided-workflow guide (Chinese)](usage_documents/event-pack-factory.md)
- [AI provider integration guide (Chinese)](usage_documents/ai-providers.md)
- [Git collaboration guide (Chinese)](usage_documents/git_use.md)
- [Agent usage guide (Chinese)](usage_documents/agent_use.md)
- [Self-hosted deployment guide (Chinese)](usage_documents/server-deploy.md)

## Contributing and support

All changes are made on personal feature branches and merged through Pull Requests; direct pushes to `main` are prohibited. The repository owner may merge their own change after all required CI checks pass. Other contributors should receive team review before merge. CI, deployment, and production health gates are never bypassed.

- [Report a reproducible bug](https://github.com/Mike-Zhuang/EventShock/issues/new/choose)
- [Propose a focused feature](https://github.com/Mike-Zhuang/EventShock/issues/new/choose)
- [Share sanitized LLM-provider compatibility feedback](https://github.com/Mike-Zhuang/EventShock/issues/new/choose)

Never include API keys, authorization headers, account identifiers, email addresses, source documents, or other personal or confidential information in a public issue.

## Data, privacy, and limitations

- The SpaceX case uses cited SEC, Nasdaq, and other declared event sources, but every price path, market depth value, flow, agent action, and counterfactual effect is synthetic model output.
- The market is a simplified single-instrument spot order book with bounded borrowing, margin, and liquidation proxies. It does not model a complete options market, cross-venue routing, clearing-member structure, or every exchange rule.
- Paired differences describe internal behavior under selected assumptions; they are not real-world causal estimates. Ten seeds are suitable for a classroom demo, not a production risk conclusion.
- An email address is personal information. Production collects it only for account access, verification, security, support, and research-data ownership—not for model prompts—and does not request names, identity documents, payment details, brokerage credentials, behavioral IP profiles, or unrelated private communication.
- Authenticated users can export the account data held by the primary database or permanently delete active account-owned records after re-entering the current password. Account deletion signs the user out; protected backups may retain a copy until scheduled expiry, and narrowly scoped security or legal records may survive only where reasonably necessary.
- Validated result-interpretation conversations are stored for cross-browser recovery and user-controlled deletion. Users must not place secrets or personal information in those prompts. Deletion removes message content while retaining only a non-content identifier hash that prevents stale-request resurrection.
- Passwords use salted scrypt digests; verification codes and session tokens are stored only as irreversible digests. Provider API keys never enter the account database.
- Event Pack Factory `PASTE` and Reader bodies are staged in an owner-isolated SQLite payload table for seven days from the latest substantive build mutation. Normal snapshots, logs, audit details, and exports exclude raw text; the owner can explicitly fetch it through a no-store review endpoint. Editing raw text creates a new revision, reruns safety checks, and resets review to `PENDING`. Rejecting a source or deleting/expiring a build removes its Factory data and attempts a WAL truncation, without deleting an already materialized Event Pack. Search, Reader, and materialization use persistent `clientRequestId + payload hash` idempotency to recover successes without duplicate dispatch.
- Search-result snippets are stored only as discovery metadata and cannot support claims. A user must approve the discovery record, retrieve the full HTTPS page through Reader, and separately review the resulting evidence source. Users must submit only material they are authorized to retain and send to the selected provider. The deterministic scanner is not an antivirus sandbox, complete attachment parser, or substitute for a privacy-compliance program.
- The clickwrap text is a versioned project draft and audit mechanism, not legal advice or a guarantee of enforceability. Qualified counsel must review the operating entity, contact channel, jurisdiction, minors/education use, and cross-border processing before broader production use.

## License

This repository is **source-available, not open source**, under the [PolyForm Strict License 1.0.0](LICENSE).

The license does not grant permission to distribute the software, modify it, or create derivative works. Other uses are allowed only within the license's stated terms, including its limited noncommercial permission; obtain separate authorization for uses outside those terms. This summary is provided for convenience and does not replace the English license text in `LICENSE`.
