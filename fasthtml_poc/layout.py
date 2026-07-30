"""Shared page chrome: navbar, full-page wrapper, and a generic DataFrame table renderer."""
from fasthtml.common import Titled, Nav, Div, Span, A, Table, Thead, Tbody, Tr, Th, Td, P
import pandas as pd

from auth import is_authenticated, get_current_user_email, is_admin

BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
PLOTLY_JS = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def render_navbar(session: dict):
    authed = is_authenticated(session)
    admin = is_admin(session)
    email = get_current_user_email(session)

    links = [A("Player Details", href='/player-details', cls='nav-link')]
    if admin:
        links.append(A("Add Match", href='/add-match', cls='nav-link'))
    if authed:
        links.append(Span(email or '', cls='navbar-text mx-2'))
        links.append(A("Logout", href='/logout', cls='nav-link'))
    else:
        links.append(A("Login", href='/login', cls='nav-link'))

    return Nav(
        Div(A("Golf Trips — FastHTML POC", href='/', cls='navbar-brand mb-0'), cls='d-flex'),
        Div(*links, cls='d-flex align-items-center gap-3'),
        cls='navbar navbar-expand d-flex justify-content-between px-3 py-2 border-bottom mb-3',
    )


def page(session: dict, title: str, *content):
    """Full-page wrapper: navbar + page content."""
    return Titled(title, render_navbar(session), *content)


def data_table(df: pd.DataFrame):
    if df is None or df.empty:
        return P("No data.", cls='text-muted')
    return Table(
        Thead(Tr(*[Th(str(c)) for c in df.columns])),
        Tbody(*[Tr(*[Td(str(v)) for v in row]) for row in df.itertuples(index=False)]),
        cls='table table-striped table-sm',
    )
