# Environment Bootstrap

## Secret handling

- Keep real secrets only in the local `.env` or your deployment secret manager.
- Do not commit `.env`; the repository template is `.env.example`.
- Rotate at least these values before any shared or production deployment:
  - `JWT_SECRET_KEY`
  - `ENCRYPTION_KEY`
  - provider API keys such as `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, and `NVIDIA_API_KEY`
- Generate strong random secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Backend bootstrap

- The backend has a repo-local bootstrap command now, so new chats or fresh shells should not require manual dependency explanation.
- Run this from the repo root when `pytest`, `mypy`, or backend imports fail because packages are missing:

```powershell
.\backend\bootstrap-dev.ps1
```

- What it does:
  - installs the backend package in editable mode
  - installs the full `dev` extra from [pyproject.toml](</c:/Projects/pre_poc_ai_crawler/backend/pyproject.toml>)
  - includes runtime-only imports that had been missing from the declared dependency set, plus type-stub packages used by `mypy`

- After bootstrap, the standard backend checks are:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests --ignore=backend/tests/e2e -q
.\backend\.venv\Scripts\python.exe -m mypy backend\app backend\harness_support.py backend\run_acquire_smoke.py backend\run_browser_surface_probe.py backend\run_extraction_smoke.py backend\run_test_sites_acceptance.py
```

## Admin bootstrap

- `BOOTSTRAP_ADMIN_ONCE=false` is the safe default.
- To bootstrap an admin intentionally, set all three:
  - `BOOTSTRAP_ADMIN_ONCE=true`
  - `DEFAULT_ADMIN_EMAIL` to a real non-placeholder email
  - `DEFAULT_ADMIN_PASSWORD` to a strong password
- The app now rejects insecure bootstrap defaults outside local dev/test environments.
- After the first successful bootstrap, turn `BOOTSTRAP_ADMIN_ONCE` back to `false`.

## Deployment note

- Non-dev environments such as `staging` and `production` must not use default secrets or placeholder bootstrap credentials.
- Startup will raise immediately if those unsafe defaults are detected.
