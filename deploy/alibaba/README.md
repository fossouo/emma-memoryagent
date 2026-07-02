# Alibaba Cloud deployment

The backend (`src/main.py` — Agent Firewall + Memory Store + Qwen Cloud
client) deploys to Alibaba Cloud Function Compute via
[`fc-service.yaml`](fc-service.yaml) (Serverless Devs format).

## Prerequisites

1. An Alibaba Cloud account with Function Compute enabled.
2. An AccessKey ID/Secret for that account.
3. The [Serverless Devs CLI](https://www.serverless-devs.com/) (`npm i -g @serverless-devs/s`).
4. A Qwen Cloud API key (see [`../../src/qwen_client.py`](../../src/qwen_client.py)).

## Steps

```bash
s config add   # paste Alibaba Cloud AccessKey ID/Secret, alias it "default"
cd deploy/alibaba
s deploy -y
```

After deploy, `s info` prints the HTTP trigger URL. Set
`QWEN_CLOUD_API_KEY` as a function environment variable (via the Function
Compute console or `s` CLI) — it is intentionally not stored in this repo.

## Status

Not yet deployed — pending Alibaba Cloud account provisioning on the
operator side. This directory defines the deployment; the live URL and a
deployment log/screenshot will be added here once run.
