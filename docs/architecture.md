# Architecture

```
                         ┌─────────────────────────────┐
  child (client) ──────► │        Agent Firewall        │
                         │  (src/agent_firewall.py)     │
                         │  - PII redaction              │
                         │  - content policy check       │
                         │  - action allow/deny           │
                         └──────────────┬────────────────┘
                                        │ allowed
                                        ▼
                         ┌─────────────────────────────┐
                         │        Memory Store          │
                         │  (src/memory_store.py)       │
                         │  per-child: preferences,     │
                         │  covered topics, praise log  │
                         └──────────────┬────────────────┘
                                        │ context injected
                                        ▼
                         ┌─────────────────────────────┐
                         │       Qwen Cloud Client       │
                         │  (src/qwen_client.py)        │
                         │  OpenAI-compatible chat API   │
                         └──────────────┬────────────────┘
                                        │
                                        ▼
                                  reply to child
```

## Deployment topology

```
                ┌───────────────────────────────────────────┐
                │              Alibaba Cloud                  │
                │                                              │
                │   ┌─────────────────────────────────────┐   │
  HTTPS ───────►│   │  Function Compute (FastAPI app)      │   │
                │   │  src/main.py                         │   │
                │   └───────────────┬───────────────────────┘   │
                │                   │ calls out to               │
                └───────────────────┼─────────────────────────────┘
                                    ▼
                          Qwen Cloud API (model inference)
```

The backend (Agent Firewall + Memory Store + API layer) runs on Alibaba
Cloud Function Compute — see [`deploy/alibaba/`](../deploy/alibaba/) for the
service definition. It calls out to Qwen Cloud for model inference only; no
child data is sent anywhere except the redacted, firewall-checked message
text needed for that single completion call.

## Why the model call is isolated

`src/qwen_client.py` is the only module that knows about Qwen Cloud
specifically. The Agent Firewall and Memory Store have no model-provider
assumptions baked in. This is deliberate: the same firewall + memory core is
meant to sit in front of either a hosted API (Qwen Cloud, this build) or a
self-hosted local SLM (e.g. Qwen 12B on school-owned hardware) for
institutional deployments that need on-prem/offline guarantees. Swapping the
transport is a change to one file, not a redesign.

## Status

| Component | Status |
|---|---|
| Agent Firewall (PII redaction, content policy, action gate) | Implemented |
| Memory Store (SQLite, per-child, structured: status/skill/support_style) | Implemented |
| Qwen Cloud client | Implemented, verified against the live API |
| Homework mode ("hints, not answers" support_style) | Implemented |
| Alibaba Cloud deployment | **LIVE**: `https://emma-megent-api-uywwrebxfc.eu-west-1.fcapp.run` (custom.debian10 runtime, bundled Python 3.10, see `deploy/alibaba/README.md`) |
| Demo video | In progress |
