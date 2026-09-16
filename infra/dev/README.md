# Local dev master key

`master.key` in this directory is a **dev-only** AES-256 key the dev
compose stack mounts into the asr-service and asr-worker containers at
`/etc/mdx/master.key`.

## Generate

```sh
openssl rand 32 > infra/dev/master.key
chmod 0400 infra/dev/master.key
```

## Never commit

`master.key` is matched by `.gitignore`. A `gitleaks` pre-commit hook also
flags it. In production the master key is provisioned by KMS — see ADR-0011.

# Dev auth signing key (IDX-A2)

`auth-signing-dev.json` is a **checked-in, dev-only** RS256 key
(kid `8b5e3d8e2576`) the compose stack mounts into auth-service as
`/etc/mdx/auth-signing.json` (`AUTH_SIGNING_KEYS_FILE`). It exists so
`MDX_IDP_MODE=native` runs locally without a secret store. It is public by
definition: anyone with the repo can mint tokens a dev stack accepts, which
is fine for `localhost` and catastrophic anywhere else.

Guards:

- `make check-dev-keys` (CI) fails if its kid or any private-key PEM
  appears under `infra/`, `deploy/`, `config/`, `.github/` or
  `.env.example` outside `infra/dev/` and the dev compose file.
- Staging/prod read `AUTH_SIGNING_KEYS_JSON` from the secret store;
  `AUTH_SIGNING_KEYS_FILE` is refused when `ENVIRONMENT=production`.

Rotate or add keys with `python scripts/ops/gen-signing-key.py`.
