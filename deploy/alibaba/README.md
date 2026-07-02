# Alibaba Cloud deployment

The backend (`src/main.py` — Agent Firewall + Memory Store + Qwen Cloud
client) deploys to Alibaba Cloud Function Compute via
[`fc-service.yaml`](fc-service.yaml) (Serverless Devs format), running as a
**Custom Runtime** (`custom.debian10`): FC proxies HTTP to our own uvicorn
process listening on `caPort: 9000`.

## Status: LIVE

`https://emma-megent-api-uywwrebxfc.eu-west-1.fcapp.run` — `/healthz` and
`/demo/` return 200. `/chat` (the only route that calls out to Qwen Cloud)
needs `QWEN_CLOUD_API_KEY` set as a function environment variable, which is
a founder decision (see below), not yet done.

## Why a bundled Python interpreter

`custom.debian10`'s system `python3` is 3.7 — incompatible with our
Python 3.10 dependency wheels. Rather than fight the base image, the
deploy vendors a **portable CPython 3.10** build
([astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone))
into `python-runtime/` and points the entrypoint at it directly. This also
makes the deploy fully reproducible regardless of what Alibaba changes in
the base image.

## Prerequisites

1. An Alibaba Cloud account with Function Compute enabled.
2. An AccessKey ID/Secret for a RAM user with `AliyunFCFullAccess` (least
   privilege — do not use the root account's keys).
3. The [Serverless Devs CLI](https://www.serverless-devs.com/) (`npm i -g @serverless-devs/s`).
4. A Qwen Cloud API key (see [`../../src/qwen_client.py`](../../src/qwen_client.py)).

## Steps

```bash
s config add   # paste Alibaba Cloud AccessKey ID/Secret, alias it "default"

# From the repo root:
bash deploy/alibaba/build.sh   # vendors Linux wheels into vendor/
# Download+extract a portable CPython 3.10 into python-runtime/ — see
# build.sh's sibling step or do it manually from python-build-standalone
# releases (x86_64-unknown-linux-gnu, install_only_stripped variant).

s -t deploy/alibaba/fc-service.yaml deploy -y
```

The entrypoint is the **`bootstrap`** file at the repo root (not
`deploy/alibaba/`) — Custom Runtime looks for a literal executable file
named `bootstrap` at the code root; `command:`/`customRuntimeConfig` in the
YAML are not used for this runtime (despite what most tutorials show).

## Setting the Qwen Cloud API key (founder-only step)

Persisting `QWEN_CLOUD_API_KEY` as a plaintext Alibaba Cloud FC environment
variable is a real, standing exposure surface (visible to anyone with
console access to this account) — a decision the founder needs to make
explicitly, not something automated silently. Once approved:

```bash
# Via the FC console: Functions → emma-memoryagent-api → Environment Variables
# — or via CLI once approved:
export QWEN_CLOUD_API_KEY="$(cat /path/to/key)"
# then wire it into fc-service.yaml's environmentVariables and redeploy,
# or set it directly via the console (does not require a redeploy).
```

## Debugging notes (fc3 v0.1.22 schema quirks)

- Function-level fields (`functionName`, `runtime`, `caPort`, `code`,
  `triggers`, etc.) live at the **props root**, not nested under
  `function:`/`triggers:` — despite most published examples.
- `codeUri` is not a valid field here; use `code`.
- `diskSize` must be `512` or a multiple of `10240`.
- `cpu:` becomes required once `memorySize` is raised above the
  free-tier default.
- Changing a deployed function's `runtime` in place is rejected by the API
  (`s remove` then `s deploy` fresh instead).
- `s invoke` only exercises the legacy event/handler path, not the caPort
  HTTP proxy — not useful for debugging this deployment mode. The actual
  useful signal was the full Python traceback embedded in the raw 502
  error body on a real HTTP request.
