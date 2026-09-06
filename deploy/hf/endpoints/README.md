# Hugging Face Inference Endpoints — declarative specs (DEP-S1)

Endpoints exist **only** from the specs in this directory. Nobody clicks in
the HF console; the console is read-only for us.

```sh
make hf-endpoints ARGS="plan --env staging"      # diff live vs spec (CI runs this on PRs when HF_TOKEN is present)
make hf-endpoints ARGS="apply --env staging"     # create/update — manual workflow with environment protection
make hf-endpoints ARGS="status --env staging"
make hf-endpoints ARGS="pause --env staging"     # scale to zero now (weekend)
make hf-endpoints ARGS="resume --env staging"
make hf-endpoints ARGS="delete --env staging --yes"
```

`scripts/models/hf_endpoints.py` talks to the Endpoints API
(`api.endpoints.huggingface.cloud/v2`) with plain HTTPS; it needs
`HF_TOKEN` (fine-grained, *Inference Endpoints: write* scope, per
environment) and `HF_NAMESPACE` (org or user). The token is read from the
environment only — never from a file in this repo.

Each spec is one endpoint. Fields map 1:1 to the API's create/update body;
`{env}` in `name` is substituted. `revision` **must** be an immutable commit
from `docs/models/PINS.md` (a spec with a branch name is rejected by the
schema). Region must be `eu-*`; `type` must be `protected` (no public
inference URL, decision 12).

After `apply`, the endpoint URL goes into the environment's secret store as
`HF_CHAT_ENDPOINT_URL` / `HF_ASR_ENDPOINT_URL` (suffix `/v1` for the chat
endpoint; `config/models.yaml` adds the route). `status` prints the URLs.

Model choice, sizes and cold-start expectations: `docs/adr/0046-*.md`
(family) and `docs/runbooks/model-backends.md` (runbook: warming, outage in
a region, token rotation, pin upgrade).
