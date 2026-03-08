# Web Session & CSRF Security Hardening

## Overview
- SessionMiddleware uses Starlette defaults: `https_only=False`, `same_site='lax'` — insecure for production OIDC flows
- Session secret derived from OIDC client_secret — functional but unconventional, no standalone SESSION_SECRET
- Single POST route (`/sync/trigger`) has zero CSRF protection
- Goal: add dedicated SESSION_SECRET, secure cookie flags, CSRF token on mutating routes

## Context
- **SessionMiddleware config:** `src/infraverse/web/app.py:109-116` — only `secret_key` and `max_age` set
- **Auth middleware:** `src/infraverse/web/middleware.py:18-42` — checks session user, excludes `/auth/*`, `/static/*`, `/health`
- **Only mutating route:** `src/infraverse/web/routes/sync.py:53` — `POST /sync/trigger`, no CSRF validation
- **Auth routes:** `src/infraverse/web/routes/auth.py` — all GET (login redirect, callback, logout)
- **Config:** `src/infraverse/config_file.py` — OidcConfig has `client_secret`, no `session_secret` field
- **Templates:** Jinja2 templates, HTMX used for trigger button

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run `python3 -m pytest tests/ -v` after each change

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Add SESSION_SECRET config and secure cookie flags
- [x] add `session_secret: str | None` to `OidcConfig` in `config_file.py` (optional, falls back to current SHA256 derivation)
- [x] add `SESSION_SECRET` env var support (checked before OIDC derivation fallback)
- [x] update SessionMiddleware in `app.py` to use: `https_only=True` (when not DEBUG), `same_site='strict'`
- [x] add `INFRAVERSE_DEBUG` or check if running on localhost to allow `https_only=False` for local dev
- [x] write tests for session secret resolution: explicit > env var > OIDC-derived
- [x] write tests for cookie flags set correctly in production vs debug mode
- [x] run tests — must pass before next task

### Task 2: Add CSRF protection to mutating routes
- [x] create `src/infraverse/web/csrf.py` with CSRF token generation (using `secrets.token_urlsafe()`) and validation
- [x] store CSRF token in session on page load (generate if absent)
- [x] add `csrf_token` to Jinja2 template context via middleware or dependency
- [x] add hidden `csrf_token` field to sync trigger form in template (or HTMX header)
- [x] validate CSRF token in `POST /sync/trigger` — reject with 403 if invalid/missing
- [x] write tests for CSRF token generation and session storage
- [x] write tests for POST rejection without valid CSRF token
- [x] write tests for POST success with valid CSRF token
- [x] run tests — must pass before next task

### Task 3: Verify acceptance criteria
- [x] verify SessionMiddleware has `https_only=True` and `same_site='strict'` in non-debug mode
- [x] verify CSRF token required on all POST routes
- [x] verify local development still works (localhost exception for https_only)
- [x] run full test suite
- [x] run linter: `ruff check src/ tests/`

### Task 4: [Final] Update documentation
- [x] update config.example.yaml with SESSION_SECRET field
- [x] update MEMORY.md if new patterns discovered

## Technical Details

### Session secret resolution order
1. `SESSION_SECRET` env var (explicit)
2. `oidc.session_secret` from YAML config
3. SHA256 of OIDC client_secret (backward-compatible fallback)

### CSRF approach
- Token stored in session (server-side, signed by SessionMiddleware)
- Validated via hidden form field or `X-CSRF-Token` header (for HTMX/fetch)
- HTMX: use `hx-headers='{"X-CSRF-Token": "..."}'` on trigger button
- No external dependency needed — stdlib `secrets` module

### Cookie flags
| Flag | Production | Local Dev |
|------|-----------|-----------|
| `https_only` | `True` | `False` |
| `same_site` | `strict` | `lax` |
| `max_age` | 14 days | 14 days |

## Post-Completion
- Test OIDC flow manually in staging environment with HTTPS
- Verify HTMX trigger button works with CSRF token
- Consider adding `Referrer-Policy` and `Content-Security-Policy` headers later
