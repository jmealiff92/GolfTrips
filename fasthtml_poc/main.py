"""FastHTML POC entrypoint: app bootstrap, OAuth/session routes, page routes.

Run from inside fasthtml_poc/: `uv sync && uv run python main.py` (serves on
:8060 by default). Reuses src/db_service_base.py, src/data_service.py, and
src/handicap_calculator.py unmodified via services.py — the existing Dash app
in src/app.py is not touched.
"""
import os

from fasthtml.common import FastHTML, RedirectResponse, JSONResponse, serve, Link, Script

from auth import oauth, build_redirect_uri
from layout import BOOTSTRAP_CSS, PLOTLY_JS
from services import db_service
from pages.player_details import player_details_page, render_player_panel
from pages.add_match import add_match_page, render_team_handicap_panel, submit_add_match

app = FastHTML(
    secret_key=os.getenv('SECRET_KEY'),
    # Distinct cookie name so this POC's login doesn't collide with the Dash
    # app's Flask session cookie when both run on localhost at once.
    session_cookie='fh_poc_session',
    same_site='lax',
    sess_https_only=False,
    hdrs=(
        Link(rel='stylesheet', href=BOOTSTRAP_CSS),
        Script(src=PLOTLY_JS),
    ),
)


@app.get('/')
def index():
    return RedirectResponse('/player-details', status_code=303)


@app.get('/health')
def health_check():
    """Port of src/app.py:134-149 — Render's health check hits this path."""
    try:
        db_service.get_years_list()
        return JSONResponse({'status': 'healthy', 'database': 'connected'})
    except Exception as e:
        return JSONResponse({'status': 'unhealthy', 'error': str(e)}, status_code=503)


# ============ Auth routes (port of src/app.py:91-121) ============

@app.get('/login')
async def login(req):
    redirect_uri = build_redirect_uri(req)
    return await oauth.google.authorize_redirect(req, redirect_uri)


@app.get('/authorize')
async def authorize(req, session):
    try:
        token = await oauth.google.authorize_access_token(req)
        resp = await oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo', token=token)
        session['user'] = resp.json()
    except Exception:
        return RedirectResponse('/login', status_code=303)
    return RedirectResponse('/', status_code=303)


@app.get('/logout')
def logout(session):
    session.pop('user', None)
    return RedirectResponse('/', status_code=303)


# ============ Player Details (port of src/app.py:607-709, 1728-1905) ============

@app.get('/player-details')
def player_details(session):
    return player_details_page(session)


@app.get('/player-details/panel')
def player_details_panel(player: str = ''):
    return render_player_panel(player)


# ============ Add Match (port of src/app.py:713-840, 1502-1724) ============

@app.get('/add-match')
def add_match_get(session):
    return add_match_page(session)


@app.get('/add-match/team-panel')
def add_match_team_panel(year: str = '', course: str = '', match_type: str = 'Single',
                          blue_player1: str = '', blue_player2: str = '',
                          red_player1: str = '', red_player2: str = ''):
    return render_team_handicap_panel(
        year, course, match_type,
        blue_player1 or None, blue_player2 or None, red_player1 or None, red_player2 or None,
    )


@app.post('/add-match')
def add_match_submit(session, year: str = '', day: str = '', match_number: str = '',
                      course: str = '', new_course: str = '', match_type: str = 'Single',
                      blue_player1: str = '', blue_player1_handicap: str = '',
                      blue_player2: str = '', blue_player2_handicap: str = '',
                      red_player1: str = '', red_player1_handicap: str = '',
                      red_player2: str = '', red_player2_handicap: str = '',
                      result: str = '', score: str = ''):
    return submit_add_match(
        session, year, day, match_number, course, new_course, match_type,
        blue_player1, blue_player1_handicap, blue_player2, blue_player2_handicap,
        red_player1, red_player1_handicap, red_player2, red_player2_handicap,
        result, score,
    )


serve(
    host=os.getenv('HOST', '0.0.0.0'),
    port=int(os.getenv('PORT', 8060)),
    reload=os.getenv('FASTHTML_RELOAD', 'true').lower() == 'true',
)
