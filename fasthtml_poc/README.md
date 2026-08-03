# FastHTML POC

A scoped proof-of-concept comparing [FastHTML](https://fastht.ml)/HTMX against the
Dash app in `src/`, covering three slices: Google OAuth login, the Player Details
page (the one page in the Dash app with a Plotly chart), and the Add Match form's
live handicap auto-calculation.

This is a spike, not a migration — it reuses `src/db_service_base.py`,
`src/data_service.py`, and `src/handicap_calculator.py` unmodified, and does not
touch the existing Dash app. It runs against the same `data/golf_trips.db` and the
same repo-root `.env`.

## Running locally

```bash
cd fasthtml_poc
uv sync
uv run python main.py
```

Serves on `http://localhost:8060` by default (override with `PORT`). The existing
Dash app can keep running on `:8050` at the same time.

## Setup notes

1. In Google Cloud Console, add a second Authorized redirect URI for your OAuth
   client: `http://localhost:8060/authorize` (alongside the existing `:8050` one).
2. This app uses a distinct session cookie name (`fh_poc_session`) so its login
   doesn't collide with the Dash app's Flask session cookie when both run on
   `localhost` at once.
3. If deployed to a Render preview (see `start_production.sh`), the OAuth redirect
   URI is derived from the incoming request host by default, but Google still
   requires that exact URL to be pre-registered as an Authorized redirect URI —
   add it manually after the first deploy, once you know the preview URL.
