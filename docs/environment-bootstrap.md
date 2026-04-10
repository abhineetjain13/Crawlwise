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
