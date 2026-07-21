import dash
from dash import dcc, html, dash_table, Input, Output, State, callback_context, no_update
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc
import os
import sys
from datetime import date
from flask import session, redirect, url_for
from dotenv import load_dotenv
import logging

# Configure logging with meaningful format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Log startup
logger.info("=" * 60)
logger.info("Golf Trips Application Starting")
logger.info("=" * 60)

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_service import get_database_service
from src.data_service import DataService
from src.handicap_calculator import HandicapCalculator
from src.auth import init_oauth, is_authenticated, get_current_user_email, is_admin

# Initialize services with correct database path
# get_database_service() will automatically choose SQLite or PostgreSQL based on .env configuration
db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'golf_trips.db')
logger.info(f"Initializing database service (path: {db_path})")
db_service = get_database_service(db_path)
logger.info(f"Database type: {type(db_service).__name__}")
data_service = DataService(db_service)
logger.info("Data service initialized successfully")

# Initialize Dash app with improved theme
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],  # Modern, clean theme
    suppress_callback_exceptions=True,
    title="Golf Trips",
    # Performance optimizations
    compress=True,  # Enable gzip compression
    update_title=None,  # Disable title updates for performance
)
logger.info("Dash app initialized with compression enabled")

# Access the Flask server and configure
server = app.server
server.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Configure session to work with Dash
server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)
logger.info("Flask server configured with session settings")

# Initialize OAuth
oauth = init_oauth(server)
logger.info("OAuth initialized for Google authentication")
logger.info("Application initialization complete")
logger.info("=" * 60)


# ============ Authentication Routes ============
@server.route('/login')
def login():
    """Redirect to Google OAuth login"""
    redirect_uri = url_for('authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@server.route('/authorize')
def authorize():
    """Handle OAuth callback"""
    try:
        oauth.google.authorize_access_token()
        # Get user info from the userinfo endpoint
        resp = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo')
        user_info = resp.json()
        session['user'] = user_info
        logger.info(f"User authenticated: {user_info.get('email', 'unknown')}")
        return redirect('/')
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        return redirect('/login')


@server.route('/logout')
def logout():
    """Logout user"""
    user_email = session.get('user', {}).get('email', 'unknown')
    session.pop('user', None)
    logger.info(f"User logged out: {user_email}")
    return redirect('/')


@server.route('/auth-status')
def auth_status():
    """Get authentication status"""
    return {
        'authenticated': is_authenticated(),
        'email': get_current_user_email(),
        'is_admin': is_admin()
    }


@server.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Quick database connectivity check
        db_service.get_years_list()
        return {
            'status': 'healthy',
            'database': 'connected'
        }, 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e)
        }, 503

# Custom CSS for better styling
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            /* Golf Green Color Scheme */
            :root {
                --golf-green-dark: #1b5e20;
                --golf-green: #2e7d32;
                --golf-green-light: #4caf50;
                --golf-green-accent: #66bb6a;
                --fairway-green: #81c784;
            }

            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 50%, #4caf50 100%);
                min-height: 100vh;
            }

            .main-container {
                background: #fafafa;
                border-radius: 15px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.15);
                margin: 20px auto;
                max-width: 1400px;
                padding: 30px;
            }

            .header-title {
                background: linear-gradient(135deg, #1b5e20 0%, #4caf50 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                font-weight: 700;
                font-size: 2.5rem;
                text-align: center;
                margin-bottom: 30px;
                text-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }

            /* Navigation Styling */
            .nav-pills .nav-link {
                border-radius: 25px;
                margin: 0 5px;
                margin-bottom: 10px;
                transition: all 0.3s ease;
                color: #2e7d32;
                font-weight: 500;
            }

            .nav-pills .nav-link.active {
                background: linear-gradient(135deg, #2e7d32 0%, #4caf50 100%) !important;
                color: white !important;
                box-shadow: 0 4px 15px rgba(46, 125, 50, 0.4);
            }

            .nav-pills .nav-link:hover:not(.active) {
                background-color: rgba(46, 125, 50, 0.1);
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            }

            /* Card Styling */
            .card {
                border: 1px solid #e0e0e0;
                box-shadow: 0 2px 10px rgba(0,0,0,0.08);
                border-radius: 10px;
                transition: all 0.3s ease;
                background: white;
            }

            .card:hover {
                box-shadow: 0 5px 20px rgba(46, 125, 50, 0.15);
                border-color: #81c784;
            }

            .card-header {
                background: linear-gradient(135deg, #f1f8f4 0%, #e8f5e9 100%);
                border-bottom: 2px solid #81c784;
                font-weight: 600;
                color: #1b5e20;
            }

            /* Button Styling */
            .btn-primary {
                background: linear-gradient(135deg, #2e7d32 0%, #4caf50 100%);
                border: none;
                border-radius: 25px;
                padding: 10px 30px;
                transition: all 0.3s ease;
                font-weight: 500;
            }

            .btn-primary:hover {
                background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%);
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(46, 125, 50, 0.4);
            }

            .btn-success {
                background: linear-gradient(135deg, #388e3c 0%, #66bb6a 100%);
                border: none;
                border-radius: 25px;
            }

            .btn-danger {
                border-radius: 25px;
            }

            /* Table Styling - Much Better! */
            .dash-table-container {
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }

            .dash-spreadsheet {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
            }

            .dash-spreadsheet-container .dash-spreadsheet-inner table {
                border-collapse: separate !important;
                border-spacing: 0 !important;
            }

            /* Table Header - Golf Green */
            .dash-header {
                background: linear-gradient(135deg, #2e7d32 0%, #4caf50 100%) !important;
                color: white !important;
                font-weight: 600 !important;
                border: none !important;
                text-align: center !important;
                padding: 12px !important;
                font-size: 0.95rem !important;
            }

            .dash-header:hover {
                background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%) !important;
            }

            /* Table Cells - Striped Rows */
            .dash-cell {
                padding: 12px !important;
                border: 1px solid #e0e0e0 !important;
                font-size: 0.9rem !important;
                transition: all 0.2s ease !important;
            }

            .dash-spreadsheet-container .dash-spreadsheet-inner tr:nth-child(even) .dash-cell {
                background-color: #f1f8f4 !important;
            }

            .dash-spreadsheet-container .dash-spreadsheet-inner tr:nth-child(odd) .dash-cell {
                background-color: white !important;
            }

            /* Hover Effect on Rows */
            .dash-spreadsheet-container .dash-spreadsheet-inner tr:hover .dash-cell {
                background-color: #e8f5e9 !important;
                cursor: pointer;
            }

            /* Selected Row */
            .dash-cell.focused {
                background-color: #c8e6c9 !important;
                border: 2px solid #4caf50 !important;
            }

            /* Active/Selected Cell */
            .dash-selected {
                background-color: #c8e6c9 !important;
            }

            /* Filter Row */
            .dash-filter {
                background-color: #f1f8f4 !important;
                border-bottom: 2px solid #4caf50 !important;
            }

            .dash-filter input {
                border: 1px solid #81c784 !important;
                border-radius: 4px !important;
                padding: 6px !important;
            }

            .dash-filter input:focus {
                border-color: #4caf50 !important;
                outline: none !important;
                box-shadow: 0 0 0 2px rgba(76, 175, 80, 0.2) !important;
            }

            /* Sort Icons */
            .column-header--sort svg {
                fill: white !important;
            }

            /* Pagination */
            .dash-spreadsheet-container .previous-next-container {
                margin-top: 10px;
            }

            .dash-spreadsheet-container button {
                background: linear-gradient(135deg, #2e7d32 0%, #4caf50 100%) !important;
                border: none !important;
                border-radius: 20px !important;
                color: white !important;
                padding: 8px 20px !important;
                margin: 0 5px !important;
            }

            .dash-spreadsheet-container button:hover {
                background: linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%) !important;
            }

            /* Alert Styling */
            .alert-success {
                background-color: #e8f5e9 !important;
                border-color: #81c784 !important;
                color: #1b5e20 !important;
                font-weight: 500 !important;
            }

            .alert-danger {
                background-color: #ffebee !important;
                border-color: #ef5350 !important;
                color: #c62828 !important;  /* Dark red for readability */
                font-weight: 500 !important;
            }

            .alert-warning {
                background-color: #fff3e0 !important;
                border-color: #ffb74d !important;
                color: #e65100 !important;  /* Dark orange for readability */
                font-weight: 500 !important;
            }

            .alert-info {
                background-color: #e3f2fd !important;
                border-color: #64b5f6 !important;
                color: #0d47a1 !important;  /* Dark blue for readability */
                font-weight: 500 !important;
            }

            /* Input Fields */
            input[type="number"], input[type="text"], .Select-control {
                border: 1px solid #c8e6c9 !important;
                border-radius: 8px !important;
                transition: all 0.3s ease !important;
            }

            input:focus, .Select-control:focus {
                border-color: #4caf50 !important;
                box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1) !important;
                outline: none !important;
            }

            /* Dropdown Styling */
            .Select-menu-outer {
                border: 1px solid #81c784 !important;
                border-radius: 8px !important;
            }

            .Select-option:hover {
                background-color: #e8f5e9 !important;
            }

            .Select-option.is-selected {
                background-color: #c8e6c9 !important;
                color: #1b5e20 !important;
            }

            /* Match Cards Styling */
            .match-card {
                transition: all 0.3s ease !important;
            }

            .match-card:hover {
                transform: translateY(-5px) !important;
                box-shadow: 0 8px 25px rgba(0,0,0,0.15) !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Layout
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='auth-store', storage_type='session'),
    dcc.Interval(id='auth-check-interval', interval=30000, n_intervals=0),  # Check auth every 30s (reduced for performance)

    html.Div([
        # Header with auth status
        html.Div([
            html.H1("⛳ Golf Trips", className='header-title', style={'display': 'inline-block', 'marginRight': '20px'}),
            html.Div(id='auth-display', style={'display': 'inline-block', 'float': 'right', 'marginTop': '20px'})
        ], style={'marginBottom': '20px'}),

        # Navigation
        dbc.Nav([
            dbc.NavLink('📊 Summary', href='/', active='exact'),
            dbc.NavLink('🏆 Matches', href='/matches', active='exact'),
            dbc.NavLink('🏳️ Teams', href='/teams', active='exact'),
            dbc.NavLink('👤 Player Details', href='/player-details', active='exact'),
            dbc.NavLink('👥 Manage Players', href='/manage-players', active='exact', id='nav-manage-players'),
            dbc.NavLink('🏌️ Manage Courses', href='/manage-courses', active='exact', id='nav-manage-courses'),
            dbc.NavLink('➕ Add Match', href='/add-match', active='exact', id='nav-add-match'),
            dbc.NavLink('✏️ Edit Matches', href='/edit-matches', active='exact', id='nav-edit-matches'),
            dbc.NavLink('⚔️ Head-to-Head', href='/head-to-head', active='exact'),
            dbc.NavLink('📈 Course Stats', href='/course-stats', active='exact'),
        ], pills=True, style={'marginBottom': '30px', 'justifyContent': 'center', 'flexWrap': 'wrap'}),

        # Alert for feedback messages
        html.Div(id='alert-container', style={'marginBottom': '20px'}),

        # Page content with loading spinner
        dcc.Loading(
            id='page-loading',
            type='default',
            color='#4caf50',
            children=html.Div(id='page-content')
        )
    ], className='main-container')
])


# ============ Page 1: Summary and Player Performance ============
def create_team_summary_page():
    partner_performance = data_service.get_partner_performace(min_matches=3)
    return html.Div([
        html.H2("Overall Team Summary"),
        dash_table.DataTable(
            id='team-summary-table',
            columns=[
                {'name': 'Year', 'id': 'Year'},
                {'name': 'Blue Points', 'id': 'Blue_Points'},
                {'name': 'Red Points', 'id': 'Red_Points'},
                {'name': 'Winner', 'id': 'Winner'}
            ],
            data=data_service.summarise_team_results().to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            style_data_conditional=[
                {
                    'if': {'filter_query': '{Winner} = "Blue"', 'column_id': 'Winner'},
                    'backgroundColor': '#cce5ff',
                    'fontWeight': 'bold'
                },
                {
                    'if': {'filter_query': '{Winner} = "Red"', 'column_id': 'Winner'},
                    'backgroundColor': '#ffcccc',
                    'fontWeight': 'bold'
                }
            ]
        ),

        html.H2("Overall Player Performance", style={'marginTop': '30px'}),
        dash_table.DataTable(
            id='player-performance-table',
            columns=[
                {'name': 'Player', 'id': 'Player'},
                {'name': 'Matches', 'id': 'Matches'},
                {'name': 'Wins', 'id': 'Wins'},
                {'name': 'Halves', 'id': 'Halves'},
                {'name': 'Losses', 'id': 'Losses'},
                {'name': 'Points', 'id': 'Points'},
                {'name': 'Win %', 'id': 'Win %'},
                {'name': 'PPG', 'id': 'PPG'}
            ],
            data=data_service.get_player_performance_all_players().to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            filter_action='native',
            page_size=20
        ),

        html.H2("Singles Match Performance", style={'marginTop': '30px'}),
        dash_table.DataTable(
            columns=[
                {'name': 'Player', 'id': 'Player'},
                {'name': 'Matches', 'id': 'Matches'},
                {'name': 'Wins', 'id': 'Wins'},
                {'name': 'Halves', 'id': 'Halves'},
                {'name': 'Losses', 'id': 'Losses'},
                {'name': 'Points', 'id': 'Points'},
                {'name': 'Win %', 'id': 'Win %'},
                {'name': 'PPG', 'id': 'PPG'}
            ],
            data=data_service.get_player_performance_all_players('Single').to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            filter_action='native',
            page_size=20
        ),

        html.H2("Fourball Match Performance", style={'marginTop': '30px'}),
        dash_table.DataTable(
            columns=[
                {'name': 'Player', 'id': 'Player'},
                {'name': 'Matches', 'id': 'Matches'},
                {'name': 'Wins', 'id': 'Wins'},
                {'name': 'Halves', 'id': 'Halves'},
                {'name': 'Losses', 'id': 'Losses'},
                {'name': 'Points', 'id': 'Points'},
                {'name': 'Win %', 'id': 'Win %'},
                {'name': 'PPG', 'id': 'PPG'}
            ],
            data=data_service.get_player_performance_all_players('Fourball').to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            filter_action='native',
            page_size=20
        ),
        html.H2("Fourball Partnerships", style={'marginTop': '30px'}),
        dash_table.DataTable(
            columns=[
                {'id':i, 'name':i} for i in [
                    'partnership','Matches','Wins','Halves',
                    'Losses','Points','PPG'
                ]
            ],
            data=partner_performance.to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            filter_action='native',
            page_size=20
        )
    ])


# ============ Page 2: Player Details ============
def create_player_details_page():
    players = sorted(data_service.players)

    return html.Div([
        html.H2("Player Details"),
        dcc.Dropdown(
            id='player-dropdown',
            options=[{'label': player, 'value': player} for player in players],
            value=players[0] if players else None,
            style={'width': '50%', 'marginBottom': '20px'}
        ),
        html.H3("Player Summary", id='player-summary-title'),
        html.Div([
            html.P(id='player-matches'),
            html.P(id='player-wins'),
            html.P(id='player-halves'),
            html.P(id='player-losses'),
            html.P(id='player-points'),
            html.P(id='player-win-pct'),
        ]),

        html.H3("Points per Year", style={'marginTop': '30px'}),
        dcc.Graph(id='player-points-chart'),

        html.H3("Course Performance", style={'marginTop': '30px'}),
        dash_table.DataTable(
            id='player-course-performance-table',
            columns=[
                {'name': 'Course', 'id': 'Course'},
                {'name': 'Matches', 'id': 'Matches'},
                {'name': 'Wins', 'id': 'Wins'},
                {'name': 'Halves', 'id': 'Halves'},
                {'name': 'Losses', 'id': 'Losses'},
                {'name': 'Points', 'id': 'Points'},
                {'name': 'PPG', 'id': 'PPG'}
            ],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            page_size=20
        ),

        html.H3("Fourball Partner Performance", style={'marginTop': '30px'}),
        dash_table.DataTable(
            id='partner-performance-table',
            columns=[
                {'id':i, 'name':i} for i in [
                    'partnership','Matches','Wins','Halves',
                    'Losses','Points','PPG'
                ]
            ],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            page_size=20
        ),

        html.H3("Performance Against Opponents", style={'marginTop': '30px'}),
        dash_table.DataTable(
            id='opponent-performance-table',
            columns=[
                {'name': 'Opponent', 'id': 'Opponent'},
                {'name': 'Matches', 'id': 'Matches'},
                {'name': 'Wins', 'id': 'Wins'},
                {'name': 'Halves', 'id': 'Halves'},
                {'name': 'Losses', 'id': 'Losses'},
                {'name': 'Points', 'id': 'Points'},
                {'name': 'PPG', 'id': 'PPG'},
                {'name': 'Win %', 'id': 'Win %'}
            ],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            page_size=20
        ),

        html.H3("Match History", style={'marginTop': '30px'}),
        dash_table.DataTable(
            id='player-match-table',
            columns=[
                {'name': 'Year', 'id': 'Year'},
                {'name': 'Day', 'id': 'Day'},
                {'name': 'Match #', 'id': 'MatchNumber'},
                {'name': 'Course', 'id': 'Course'},
                {'name': 'Match Type', 'id': 'MatchType'},
                {'name': 'Result', 'id': 'Result'},
                {'name': 'Score', 'id': 'Score'},
                {'name': 'Player Team', 'id': 'Player_Team'},
                {'name': 'Outcome', 'id': 'Outcome'}
            ],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native',
            filter_action='native',
            page_size=25
        )
    ])


# ============ Page 3: Add Match Form ============
def create_add_match_page():
    # Get all players from players table (not just those in matches)
    players = sorted(db_service.get_all_players())
    current_year = date.today().year
    # Get courses from courses table (not just those in matches)
    all_courses = db_service.get_all_courses()
    courses = [c['name'] for c in all_courses]

    return html.Div([
        html.H2("Add New Match"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Year"),
                        dbc.Input(id='input-year', type='number', value=current_year, min=2018, max=2030)
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Day"),
                        dbc.Input(id='input-day', type='number', value=1, min=1, max=10)
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Match Number"),
                        dbc.Input(id='input-match-number', type='number', value=1, min=1, max=20)
                    ], width=4),
                ], className='mb-3'),

                dbc.Row([
                    dbc.Col([
                        dbc.Label("Course"),
                        dcc.Dropdown(
                            id='input-course',
                            options=[{'label': c, 'value': c} for c in courses] + [{'label': '+ Add New Course', 'value': 'NEW'}],
                            value=courses[0] if courses else None,
                            clearable=False
                        ),
                        dbc.Input(id='input-new-course', placeholder='Enter new course name', style={'marginTop': '10px', 'display': 'none'})
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Match Type"),
                        dcc.Dropdown(
                            id='input-match-type',
                            options=[
                                {'label': 'Single', 'value': 'Single'},
                                {'label': 'Fourball', 'value': 'Fourball'}
                            ],
                            value='Single',
                            clearable=False
                        )
                    ], width=6),
                ], className='mb-3'),

                html.H4("Blue Team", className='mt-3', style={'color': '#0066cc'}),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Player 1"),
                        dcc.Dropdown(id='input-blue-player1', options=[{'label': p, 'value': p} for p in players])
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Match Handicap"),
                        dbc.Input(id='input-blue-player1-handicap', type='number', value=0, step=0.5)
                    ], width=6),
                ], className='mb-3'),

                html.Div(id='blue-player2-section', children=[
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Player 2"),
                            dcc.Dropdown(id='input-blue-player2', options=[{'label': p, 'value': p} for p in players])
                        ], width=6),
                        dbc.Col([
                            dbc.Label("Match Handicap"),
                            dbc.Input(id='input-blue-player2-handicap', type='number', value=0, step=0.5)
                        ], width=6),
                    ], className='mb-3'),
                ]),

                html.H4("Red Team", className='mt-3', style={'color': '#cc0000'}),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Player 1"),
                        dcc.Dropdown(id='input-red-player1', options=[{'label': p, 'value': p} for p in players])
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Match Handicap"),
                        dbc.Input(id='input-red-player1-handicap', type='number', value=0, step=0.5)
                    ], width=6),
                ], className='mb-3'),

                html.Div(id='red-player2-section', children=[
                    dbc.Row([
                        dbc.Col([
                            dbc.Label("Player 2"),
                            dcc.Dropdown(id='input-red-player2', options=[{'label': p, 'value': p} for p in players])
                        ], width=6),
                        dbc.Col([
                            dbc.Label("Match Handicap"),
                            dbc.Input(id='input-red-player2-handicap', type='number', value=0, step=0.5)
                        ], width=6),
                    ], className='mb-3'),
                ]),

                html.H4("Result (Optional)", className='mt-3'),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Winner"),
                        dcc.Dropdown(
                            id='input-result',
                            options=[
                                {'label': 'Blue', 'value': 'Blue'},
                                {'label': 'Red', 'value': 'Red'},
                                {'label': 'Half', 'value': 'Half'},
                                {'label': 'TBD', 'value': ''}
                            ],
                            value='',
                            clearable=False
                        )
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Score (e.g., 3&2, A/S)"),
                        dbc.Input(id='input-score', placeholder='e.g., 3&2, 1UP, A/S')
                    ], width=6),
                ], className='mb-3'),

                dbc.Button("Add Match", id='btn-add-match', color='primary', size='lg', className='mt-3')
            ])
        ], className='shadow')
    ])


# ============ Page 4: Head-to-Head ============
def create_head_to_head_page():
    players = sorted(data_service.players)

    return html.Div([
        html.H2("Head-to-Head Statistics"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Player 1"),
                        dcc.Dropdown(
                            id='h2h-player1',
                            options=[{'label': p, 'value': p} for p in players],
                            value=players[0] if players else None
                        )
                    ], width=5),
                    dbc.Col([
                        html.Div('VS', style={'textAlign': 'center', 'fontSize': '24px', 'fontWeight': 'bold', 'marginTop': '30px'})
                    ], width=2),
                    dbc.Col([
                        dbc.Label("Player 2"),
                        dcc.Dropdown(
                            id='h2h-player2',
                            options=[{'label': p, 'value': p} for p in players],
                            value=players[1] if len(players) > 1 else None
                        )
                    ], width=5),
                ])
            ])
        ], className='shadow mb-4'),

        html.Div(id='h2h-results')
    ])


# ============ Page 5: Course Statistics ============
def create_course_stats_page():
    course_stats = data_service.get_course_statistics()

    return html.Div([
        html.H2("Course Statistics"),
        dash_table.DataTable(
            columns=[
                {'name': 'Course', 'id': 'Course'},
                {'name': 'Matches Played', 'id': 'Matches'},
                {'name': 'Blue Wins', 'id': 'Blue_Wins'},
                {'name': 'Red Wins', 'id': 'Red_Wins'},
                {'name': 'Halves', 'id': 'Halves'}
            ],
            data=course_stats.to_dict('records'),
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            sort_action='native'
        )
    ])


# ============ Page 6: Manage Players ============
def create_manage_players_page():
    players = db_service.get_all_players_with_handicaps()
    current_year = date.today().year

    return html.Div([
        html.H2("Manage Players"),

        # Add New Player Section
        dbc.Card([
            dbc.CardHeader(html.H4("Add New Player")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Player Name"),
                        dbc.Input(id='new-player-name', placeholder='Enter player name')
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Year"),
                        dbc.Input(id='new-player-year', type='number', value=current_year, min=2018, max=2030)
                    ], width=3),
                    dbc.Col([
                        dbc.Label("Handicap Index"),
                        dbc.Input(id='new-player-handicap', type='number', step=0.1, placeholder='e.g., 12.5')
                    ], width=3),
                ], className='mb-3'),
                dbc.Button("Add Player", id='btn-add-player', color='primary')
            ])
        ], className='shadow mb-4'),

        # Manage Existing Players Section
        dbc.Card([
            dbc.CardHeader(html.H4("Manage Player")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Select Player"),
                        dcc.Dropdown(
                            id='manage-player-dropdown',
                            options=[{'label': p['name'], 'value': p['name']} for p in players],
                            placeholder='Select a player'
                        )
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Year"),
                        dbc.Input(id='manage-player-year', type='number', value=current_year, min=2018, max=2030)
                    ], width=3),
                ], className='mb-3'),

                html.Hr(),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Handicap Index"),
                        dbc.Input(id='manage-player-handicap', type='number', step=0.1, placeholder='e.g., 12.5')
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Team (Red/Blue)"),
                        dcc.Dropdown(
                            id='manage-player-team',
                            options=[
                                {'label': 'Blue', 'value': 'Blue'},
                                {'label': 'Red', 'value': 'Red'}
                            ],
                            placeholder='Select team'
                        )
                    ], width=6),
                ], className='mb-3'),

                dbc.Row([
                    dbc.Col([
                        dbc.Button("Save Handicap & Team", id='btn-update-player', color='success', className='me-2'),
                        dbc.Button("Delete Handicap", id='btn-delete-handicap', color='danger', className='me-2'),
                        dbc.Button("Remove Team Assignment", id='btn-delete-team', color='danger')
                    ])
                ]),
            ])
        ], className='shadow mb-4'),

        # Display Player Handicaps
        html.H3("All Players and Handicaps", className='mt-4'),
        html.Div(id='player-handicaps-display')
    ])


# ============ Page 7: Manage Courses ============
def create_manage_courses_page():
    courses = db_service.get_all_courses()

    return html.Div([
        html.H2("Manage Courses"),

        # Add/Edit Course Section
        dbc.Card([
            dbc.CardHeader(html.H4("Add or Edit Course")),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Course Name"),
                        dbc.Input(id='course-name', placeholder='Enter course name')
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Par"),
                        dbc.Input(id='course-par', type='number', value=72, min=60, max=80)
                    ], width=2),
                    dbc.Col([
                        dbc.Label("Slope Rating"),
                        dbc.Input(id='course-slope', type='number', value=113, min=55, max=155, step=1)
                    ], width=2),
                    dbc.Col([
                        dbc.Label("Course Rating"),
                        dbc.Input(id='course-rating', type='number', value=72.0, min=60.0, max=80.0, step=0.1)
                    ], width=2),
                ], className='mb-3'),
                dbc.Row([
                    dbc.Col([
                        dbc.Button("Add Course", id='btn-add-course', color='primary', className='me-2'),
                        dbc.Button("Update Course", id='btn-update-course', color='success', className='me-2'),
                        dbc.Button("Delete Course", id='btn-delete-course', color='danger')
                    ])
                ])
            ])
        ], className='shadow mb-4'),

        # Display All Courses
        html.H3("All Courses", className='mt-4'),
        dash_table.DataTable(
            id='courses-table',
            columns=[
                {'name': 'Course Name', 'id': 'name'},
                {'name': 'Par', 'id': 'par'},
                {'name': 'Slope Rating', 'id': 'slope_rating'},
                {'name': 'Course Rating', 'id': 'course_rating'}
            ],
            data=[{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                   'course_rating': c['course_rating']} for c in courses],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '10px'},
            style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
            row_selectable='single',
            selected_rows=[],
            sort_action='native',
            page_size=20
        )
    ])


# ============ Page 8: Matches Display ============
def create_matches_page():
    """Create a page displaying all matches as colored cards"""
    # Get all years for the dropdown
    years = sorted(db_service.get_years_list(), reverse=True)
    
    return html.Div([
        html.H2("All Matches", style={'marginBottom': '30px', 'textAlign': 'center'}),
        
        # Year filter section
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Filter by Year:", style={'fontWeight': 'bold', 'marginBottom': '10px'}),
                        dcc.Dropdown(
                            id='matches-year-filter',
                            options=[{'label': 'All Years', 'value': 'all'}] + 
                                   [{'label': str(year), 'value': year} for year in years],
                            value='all',
                            clearable=False,
                            style={'width': '200px'}
                        )
                    ], width=12, style={'textAlign': 'center'})
                ])
            ])
        ], className="shadow mb-4"),
        
        # Matches display container
        html.Div(id='matches-display-container')
    ])


def create_match_card(match, show_year=True):
    """Helper function to create a match card"""
    # Determine card color based on result
    result = match.get('Result', '')
    if result == 'Blue':
        card_bg_color = '#e3f2fd'  # Light blue background
        border_color = '#1976d2'   # Darker blue border
        header_bg_color = '#1976d2'  # Blue header
        text_color = '#0d47a1'     # Dark blue text
    elif result == 'Red':
        card_bg_color = '#ffebee'  # Light red background
        border_color = '#d32f2f'   # Darker red border
        header_bg_color = '#d32f2f'  # Red header
        text_color = '#c62828'     # Dark red text
    elif result == 'Half':
        card_bg_color = '#f5f5f5'  # Light grey background
        border_color = '#616161'   # Darker grey border
        header_bg_color = '#616161'  # Grey header
        text_color = '#424242'     # Dark grey text
    else:  # TBD or empty
        card_bg_color = '#fafafa'  # Very light grey background
        border_color = '#9e9e9e'   # Light grey border
        header_bg_color = '#9e9e9e'  # Light grey header
        text_color = '#757575'     # Medium grey text
    
    # Format team information with sorted names
    blue_players = [match['BluePlayer1']]
    if pd.notna(match.get('BluePlayer2')) and match['BluePlayer2'] not in ['N/A', 'Ghost', '']:
        blue_players.append(match['BluePlayer2'])
    blue_team = " & ".join(sorted(blue_players))
    
    red_players = [match['RedPlayer1']]
    if pd.notna(match.get('RedPlayer2')) and match['RedPlayer2'] not in ['N/A', 'Ghost', '']:
        red_players.append(match['RedPlayer2'])
    red_team = " & ".join(sorted(red_players))
    
    # Format score
    score = match.get('Score', '')
    if not score or score in ['N/A', '']:
        score = 'TBD'
    
    # Create header title
    if show_year:
        header_title = f"Year {match['Year']} - Match {match['MatchNumber']}"
    else:
        header_title = f"Match {match['MatchNumber']}"
    
    # Create the card
    return dbc.Card([
        dbc.CardHeader([
            html.H5(header_title, className="mb-0", style={'color': 'dark-green', 'fontWeight': 'bold'})
        ], style={'backgroundColor': header_bg_color, 'color': 'dark-green'}),
        dbc.CardBody([
            html.H6(f"🏌️ {match['Course']}", className="card-title"),
            html.P(f"📅 {match['MatchType']} Match", className="card-text"),
            html.Hr(),
            html.Div([
                html.Div([
                    html.Strong("Blue Team:", style={'color': '#1976d2'}),
                    html.Br(),
                    html.Span(blue_team)
                ], style={'textAlign': 'left', 'display': 'inline-block', 'width': '45%'}),
                html.Div([
                    html.Strong("Red Team:", style={'color': '#d32f2f'}),
                    html.Br(),
                    html.Span(red_team)
                ], style={'textAlign': 'right', 'display': 'inline-block', 'width': '45%'})
            ]),
            html.Hr(),
            html.Div([
                html.Strong("Result: "),
                html.Span(result if result else 'TBD', 
                         style={'fontWeight': 'bold', 'color': text_color})
            ], style={'textAlign': 'center'}),
            html.Div([
                html.Strong("Score: "),
                html.Span(score, style={'fontWeight': 'bold', 'color': text_color})
            ], style={'textAlign': 'center', 'marginTop': '10px'})
        ], style={'backgroundColor': card_bg_color})
    ], 
    style={
        'border': f'3px solid {border_color}',
        'marginBottom': '20px',
        'boxShadow': f'0 4px 8px rgba(0,0,0,0.1)',
        'transition': 'transform 0.2s ease-in-out',
        'backgroundColor': card_bg_color
    },
    className="match-card")


# ============ Page: Teams ============
def create_teams_page():
    """Create a page displaying the Red/Blue team rosters with handicaps for a selected year"""
    # Years come from matches, existing team assignments, and today's real year,
    # so a roster can be drafted for a year before any matches exist for it.
    real_current_year = date.today().year
    years = sorted(
        set(db_service.get_years_list()) | set(db_service.get_team_years_list()) | {real_current_year},
        reverse=True
    )
    current_year = real_current_year if real_current_year in years else years[0]

    return html.Div([
        html.H2("Team Rosters", style={'marginBottom': '30px', 'textAlign': 'center'}),

        # Year filter section
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Select Year:", style={'fontWeight': 'bold', 'marginBottom': '10px'}),
                        dcc.Dropdown(
                            id='teams-year-filter',
                            options=[{'label': str(year), 'value': year} for year in years],
                            value=current_year,
                            clearable=False,
                            style={'width': '200px'}
                        )
                    ], width=12, style={'textAlign': 'center'})
                ])
            ])
        ], className="shadow mb-4"),

        # Teams display container
        html.Div(id='teams-display-container')
    ])


def create_team_roster_card(team_name, players):
    """Helper function to build a team roster card with player handicaps, matching the Matches page color scheme"""
    if team_name == 'Blue':
        card_bg_color = '#e3f2fd'  # Light blue background
        border_color = '#1976d2'   # Darker blue border
        header_bg_color = '#1976d2'  # Blue header
        text_color = '#0d47a1'     # Dark blue text
    else:  # Red
        card_bg_color = '#ffebee'  # Light red background
        border_color = '#d32f2f'   # Darker red border
        header_bg_color = '#d32f2f'  # Red header
        text_color = '#c62828'     # Dark red text

    if players:
        rows = []
        for p in players:
            hcp = p.get('handicap_index')
            hcp_text = f"{hcp:.1f}" if pd.notna(hcp) else "N/A"
            rows.append(
                html.Div([
                    html.Span(p['name'], style={'fontWeight': '500', 'color': text_color}),
                    html.Span(hcp_text, style={'float': 'right', 'fontWeight': 'bold', 'color': text_color})
                ], style={'padding': '10px 5px', 'borderBottom': f'1px solid {border_color}33'})
            )
        body = rows
    else:
        body = [html.P("No players assigned yet", className='text-muted mb-0')]

    return dbc.Card([
        dbc.CardHeader([
            html.H4(f"{team_name} Team ({len(players)})", className='mb-0', style={'color': 'dark-green', 'fontWeight': 'bold'})
        ], style={'backgroundColor': header_bg_color, 'color': 'dark-green'}),
        dbc.CardBody(body, style={'backgroundColor': card_bg_color})
    ],
    style={
        'border': f'3px solid {border_color}',
        'marginBottom': '20px',
        'boxShadow': '0 4px 8px rgba(0,0,0,0.1)',
        'transition': 'transform 0.2s ease-in-out',
        'backgroundColor': card_bg_color
    },
    className="match-card")


# ============ Page 9: Edit Matches ============
def create_edit_matches_page():
    return html.Div([
        html.H2("Edit Match Results"),

        # Filter Section
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Filter by Year"),
                        dcc.Dropdown(
                            id='edit-match-year-filter',
                            options=[{'label': 'All Years', 'value': 'all'}] +
                                    [{'label': str(year), 'value': year} for year in db_service.get_years_list()],
                            value='all'
                        )
                    ], width=4),
                ])
            ])
        ], className='shadow mb-4'),

        # Matches Table
        html.Div([
            dash_table.DataTable(
                id='matches-edit-table',
                columns=[
                    {'name': 'Year', 'id': 'Year'},
                    {'name': 'Day', 'id': 'Day'},
                    {'name': 'Match #', 'id': 'MatchNumber'},
                    {'name': 'Course', 'id': 'Course'},
                    {'name': 'Type', 'id': 'MatchType'},
                    {'name': 'Blue Team', 'id': 'Blue Team'},
                    {'name': 'Red Team', 'id': 'Red Team'},
                    {'name': 'Result', 'id': 'Result'},
                    {'name': 'Score', 'id': 'Score'},
                ],
                data=[],
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'left', 'padding': '10px'},
                style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
                row_selectable='single',
                selected_rows=[],
                page_size=20,
                sort_action='native',
                filter_action='native'
            )
        ], id='edit-matches-table-container'),

        # Edit Match Modal
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Edit Match Result")),
            dbc.ModalBody([
                html.Div(id='edit-match-info'),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Result"),
                        dcc.Dropdown(
                            id='edit-match-result',
                            options=[
                                {'label': 'Blue', 'value': 'Blue'},
                                {'label': 'Red', 'value': 'Red'},
                                {'label': 'Half', 'value': 'Half'}
                            ]
                        )
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Score"),
                        dbc.Input(id='edit-match-score', placeholder='e.g., 3&2, 1UP, A/S')
                    ], width=6),
                ], className='mb-3'),
            ]),
            dbc.ModalFooter([
                dbc.Button("Save", id='btn-save-match-edit', color='primary', className='me-2'),
                dbc.Button("Delete Match", id='btn-delete-match', color='danger', className='me-2'),
                dbc.Button("Close", id='btn-close-edit-modal', color='secondary')
            ]),
        ], id='edit-match-modal', is_open=False, size='lg'),

        # Hidden div to store selected match info
        html.Div(id='selected-match-store', style={'display': 'none'})
    ])


# ============ Callbacks ============

# Page routing
@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    if pathname == '/matches':
        return create_matches_page()
    elif pathname == '/teams':
        return create_teams_page()
    elif pathname == '/player-details':
        return create_player_details_page()
    elif pathname == '/manage-players':
        return create_manage_players_page()
    elif pathname == '/manage-courses':
        return create_manage_courses_page()
    elif pathname == '/add-match':
        return create_add_match_page()
    elif pathname == '/edit-matches':
        return create_edit_matches_page()
    elif pathname == '/head-to-head':
        return create_head_to_head_page()
    elif pathname == '/course-stats':
        return create_course_stats_page()
    return create_team_summary_page()


# Show/hide player 2 fields based on match type
@app.callback(
    [Output('blue-player2-section', 'style'),
     Output('red-player2-section', 'style')],
    Input('input-match-type', 'value')
)
def toggle_player2_fields(match_type):
    if match_type == 'Single':
        return {'display': 'none'}, {'display': 'none'}
    return {'display': 'block'}, {'display': 'block'}


# Show/hide new course input
@app.callback(
    Output('input-new-course', 'style'),
    Input('input-course', 'value')
)
def toggle_new_course_input(course_value):
    if course_value == 'NEW':
        return {'marginTop': '10px', 'display': 'block'}
    return {'marginTop': '10px', 'display': 'none'}


# Restrict player dropdowns to each player's assigned team for the selected year
@app.callback(
    [Output('input-blue-player1', 'options'),
     Output('input-blue-player1', 'value'),
     Output('input-blue-player2', 'options'),
     Output('input-blue-player2', 'value'),
     Output('input-red-player1', 'options'),
     Output('input-red-player1', 'value'),
     Output('input-red-player2', 'options'),
     Output('input-red-player2', 'value')],
    Input('input-year', 'value'),
    [State('input-blue-player1', 'value'),
     State('input-blue-player2', 'value'),
     State('input-red-player1', 'value'),
     State('input-red-player2', 'value')],
    prevent_initial_call=False
)
def filter_players_by_team(year, blue_p1, blue_p2, red_p1, red_p2):
    """Limit each team's player options to players assigned to that team for the year"""
    all_options = [{'label': p, 'value': p} for p in sorted(db_service.get_all_players())]

    blue_options, red_options = all_options, all_options
    if year:
        assignments = db_service.get_team_assignments_by_year(year)
        blue_players = sorted(a['name'] for a in assignments if a['team'] == 'Blue')
        red_players = sorted(a['name'] for a in assignments if a['team'] == 'Red')
        if blue_players:
            blue_options = [{'label': p, 'value': p} for p in blue_players]
        if red_players:
            red_options = [{'label': p, 'value': p} for p in red_players]

    blue_values = {opt['value'] for opt in blue_options}
    red_values = {opt['value'] for opt in red_options}

    blue_p1 = blue_p1 if blue_p1 in blue_values else None
    blue_p2 = blue_p2 if blue_p2 in blue_values else None
    red_p1 = red_p1 if red_p1 in red_values else None
    red_p2 = red_p2 if red_p2 in red_values else None

    return blue_options, blue_p1, blue_options, blue_p2, red_options, red_p1, red_options, red_p2


# Auto-calculate handicaps when players and course are selected
@app.callback(
    [Output('input-blue-player1-handicap', 'value'),
     Output('input-blue-player2-handicap', 'value'),
     Output('input-red-player1-handicap', 'value'),
     Output('input-red-player2-handicap', 'value')],
    [Input('input-year', 'value'),
     Input('input-course', 'value'),
     Input('input-match-type', 'value'),
     Input('input-blue-player1', 'value'),
     Input('input-blue-player2', 'value'),
     Input('input-red-player1', 'value'),
     Input('input-red-player2', 'value')],
    prevent_initial_call=False
)
def auto_calculate_handicaps(year, course, match_type, blue_p1, blue_p2, red_p1, red_p2):
    """Auto-calculate match handicaps based on player handicap indexes and course"""

    # Return zeros if essential info is missing
    if not year or not course or course == 'NEW' or not blue_p1 or not red_p1:
        return 0, 0, 0, 0

    # Get course details
    course_info = db_service.get_course(course)
    if not course_info:
        return 0, 0, 0, 0

    try:
        # Get player handicap indexes for the year
        blue_p1_index = db_service.get_player_handicap(blue_p1, year)
        red_p1_index = db_service.get_player_handicap(red_p1, year)

        if blue_p1_index is None or red_p1_index is None:
            return 0, 0, 0, 0

        if match_type == 'Single':
            # Calculate for singles
            handicaps = HandicapCalculator.calculate_match_handicaps(
                match_type='Single',
                handicap_index_p1=blue_p1_index,
                handicap_index_p2=None,
                handicap_index_p3=red_p1_index,
                handicap_index_p4=None,
                slope_rating=course_info['slope_rating'],
                par=course_info['par']
            )
            return handicaps[0], 0, handicaps[1], 0

        elif match_type == 'Fourball':
            # Get all player handicaps
            if not blue_p2 or not red_p2:
                return 0, 0, 0, 0

            blue_p2_index = db_service.get_player_handicap(blue_p2, year)
            red_p2_index = db_service.get_player_handicap(red_p2, year)

            if blue_p2_index is None or red_p2_index is None:
                return 0, 0, 0, 0

            # Calculate for fourball
            handicaps = HandicapCalculator.calculate_match_handicaps(
                match_type='Fourball',
                handicap_index_p1=blue_p1_index,
                handicap_index_p2=blue_p2_index,
                handicap_index_p3=red_p1_index,
                handicap_index_p4=red_p2_index,
                slope_rating=course_info['slope_rating'],
                par=course_info['par']
            )
            return handicaps[0], handicaps[1], handicaps[2], handicaps[3]

    except Exception as e:
        print(f"Error calculating handicaps: {e}")
        return 0, 0, 0, 0

    return 0, 0, 0, 0


# Add match
@app.callback(
    Output('alert-container', 'children'),
    Input('btn-add-match', 'n_clicks'),
    [State('input-year', 'value'),
     State('input-day', 'value'),
     State('input-match-number', 'value'),
     State('input-course', 'value'),
     State('input-new-course', 'value'),
     State('input-match-type', 'value'),
     State('input-blue-player1', 'value'),
     State('input-blue-player1-handicap', 'value'),
     State('input-blue-player2', 'value'),
     State('input-blue-player2-handicap', 'value'),
     State('input-red-player1', 'value'),
     State('input-red-player1-handicap', 'value'),
     State('input-red-player2', 'value'),
     State('input-red-player2-handicap', 'value'),
     State('input-result', 'value'),
     State('input-score', 'value')],
    prevent_initial_call=True
)
def add_match(n_clicks, year, day, match_number, course, new_course, match_type,
              blue_p1, blue_p1_hcp, blue_p2, blue_p2_hcp,
              red_p1, red_p1_hcp, red_p2, red_p2_hcp, result, score):
    if not n_clicks:
        return None

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        return error_alert

    # Validate required fields
    if not all([year, day, match_number, blue_p1, red_p1]):
        return dbc.Alert("Please fill in all required fields", color="danger", dismissable=True, duration=4000)

    # Check if match already exists
    if db_service.check_match_exists(year, day, match_number):
        return dbc.Alert(
            f"Match already exists! Year {year}, Day {day}, Match {match_number} is already in the database. "
            f"Please use a different match number or edit the existing match.",
            color="danger", dismissable=True, duration=6000
        )

    # Use new course name if selected
    if course == 'NEW':
        if not new_course:
            return dbc.Alert("Please enter a course name", color="danger", dismissable=True, duration=4000)
        course = new_course

    # For singles, ignore player 2 fields
    if match_type == 'Single':
        blue_p2 = None
        blue_p2_hcp = None
        red_p2 = None
        red_p2_hcp = None

    # Add match to database
    success = db_service.add_match(
        year=year, day=day, match_number=match_number,
        course=course, match_type=match_type,
        blue_player1=blue_p1, blue_player1_handicap=blue_p1_hcp or 0,
        blue_player2=blue_p2, blue_player2_handicap=blue_p2_hcp,
        red_player1=red_p1, red_player1_handicap=red_p1_hcp or 0,
        red_player2=red_p2, red_player2_handicap=red_p2_hcp,
        result=result, score=score
    )

    if success:
        data_service.invalidate_cache()  # Clear cache
        return dbc.Alert(
            f"Match added successfully! Year {year}, Day {day}, Match {match_number}",
            color="success", dismissable=True, duration=4000
        )
    else:
        return dbc.Alert(
            "Failed to add match. A match with this Year/Day/Match Number may already exist.",
            color="danger", dismissable=True, duration=4000
        )


# Player details callbacks
@app.callback(
    [Output('player-summary-title', 'children'),
     Output('player-matches', 'children'),
     Output('player-wins', 'children'),
     Output('player-halves', 'children'),
     Output('player-losses', 'children'),
     Output('player-points', 'children'),
     Output('player-win-pct', 'children'),
     Output('player-points-chart', 'figure'),
     Output('player-match-table', 'data'),
     Output('partner-performance-table', 'data'),
     Output('opponent-performance-table', 'data'),
     Output('player-course-performance-table', 'data')],
    Input('player-dropdown', 'value')
)
def update_player_details(player):
    if not player:
        return [""] * 12

    results = data_service.build_results_per_player()
    player_results = results[results['Player'] == player]

    # Summary stats
    stats = player_results['Result'].value_counts().to_dict()
    wins = stats.get('Win', 0)
    halves = stats.get('Half', 0)
    losses = stats.get('Loss', 0)
    points = wins + (halves * 0.5)
    win_pct = ((wins + (halves / 2)) / len(player_results) * 100) if len(player_results) > 0 else 0

    # Player matches
    df = data_service.df
    player_matches = df[
        (df['BluePlayer1'] == player) | (df['BluePlayer2'] == player) |
        (df['RedPlayer1'] == player) | (df['RedPlayer2'] == player)
    ].copy()

    player_matches['Player_Team'] = player_matches.apply(
        lambda row: 'Blue' if player in [row['BluePlayer1'], row['BluePlayer2']] else 'Red', axis=1
    )
    player_matches['Outcome'] = player_matches.apply(
        lambda row: 'Win' if row['Result'] == row['Player_Team']
        else ('Loss' if row['Result'] != 'Half' else 'Half'), axis=1
    )

    # Points per year chart
    yearly_points = player_matches.groupby('Year')['Outcome'].value_counts().unstack(fill_value=0)
    yearly_points['Points'] = yearly_points.get('Win', 0) + (yearly_points.get('Half', 0) * 0.5)
    yearly_points = yearly_points.reset_index()[['Year', 'Points']]

    yearly_points['Handicap'] = yearly_points['Year'].apply(
        lambda year: db_service.get_player_handicap(player, int(year))
    )

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=yearly_points['Year'], y=yearly_points['Points'],
            name='Points', marker_color='#1e90ff'
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=yearly_points['Year'], y=yearly_points['Handicap'],
            name='Handicap Index', mode='lines+markers',
            marker_color='#ff8c00', connectgaps=True
        ),
        secondary_y=True
    )
    fig.update_layout(
        title=f"{player}'s Points per Year",
        xaxis_title="Year"
    )
    fig.update_yaxes(
        title_text="Points", secondary_y=False,
        range=[0, max(yearly_points['Points']) + 1] if len(yearly_points) > 0 else None
    )
    fig.update_yaxes(title_text="Handicap Index", secondary_y=True, showgrid=False)

    # Course performance
    course_perf = data_service.get_player_course_performance(player)

    # Fourball partner performance
    partner_stats_df = data_service.get_partner_performace(player)

    # Opponent performance
    opponent_stats = []
    opponents = set()

    for _, row in player_matches.iterrows():
        # Identify opponents (players on the opposite team)
        if row['Player_Team'] == 'Blue':
            opp1 = row['RedPlayer1']
            opp2 = row['RedPlayer2']
        else:
            opp1 = row['BluePlayer1']
            opp2 = row['BluePlayer2']

        # Add non-empty opponents
        for opp in [opp1, opp2]:
            if pd.notna(opp) and opp not in ['N/A', 'Ghost', '']:
                opponents.add(opp)

    # Calculate stats for each opponent
    for opponent in opponents:
        # Find all matches where player faced this opponent
        opp_matches = player_matches[
            ((player_matches['Player_Team'] == 'Blue') &
             ((player_matches['RedPlayer1'] == opponent) | (player_matches['RedPlayer2'] == opponent))) |
            ((player_matches['Player_Team'] == 'Red') &
             ((player_matches['BluePlayer1'] == opponent) | (player_matches['BluePlayer2'] == opponent)))
        ]

        if len(opp_matches) > 0:
            opp_stats = opp_matches['Outcome'].value_counts().to_dict()
            opp_wins = opp_stats.get('Win', 0)
            opp_halves = opp_stats.get('Half', 0)
            opp_losses = opp_stats.get('Loss', 0)
            opp_points = opp_wins + (opp_halves * 0.5)
            ppg = opp_points / len(opp_matches)
            opp_win_pct = ((opp_wins + (opp_halves * 0.5)) / len(opp_matches) * 100) if len(opp_matches) > 0 else 0

            opponent_stats.append({
                'Opponent': opponent,
                'Matches': len(opp_matches),
                'Wins': opp_wins,
                'Halves': opp_halves,
                'Losses': opp_losses,
                'Points': opp_points,
                'PPG': round(ppg, 2),
                'Win %': f"{opp_win_pct:.1f}%"
            })

    opponent_stats_df = pd.DataFrame(opponent_stats).sort_values('PPG', ascending=False) if opponent_stats else pd.DataFrame()

    return (
        f"{player} Summary",
        f"Matches: {len(player_matches)}",
        f"Wins: {wins}",
        f"Halves: {halves}",
        f"Losses: {losses}",
        f"Points: {points:.1f}",
        f"Win Percentage: {win_pct:.1f}%",
        fig,
        player_matches[['Year', 'Day', 'MatchNumber', 'Course', 'MatchType',
                       'Result', 'Score', 'Player_Team', 'Outcome']].to_dict('records'),
        partner_stats_df.to_dict('records') if not partner_stats_df.empty else [],
        opponent_stats_df.to_dict('records') if not opponent_stats_df.empty else [],
        course_perf.to_dict('records')
    )


# Head-to-head callback
@app.callback(
    Output('h2h-results', 'children'),
    [Input('h2h-player1', 'value'),
     Input('h2h-player2', 'value')]
)
def update_head_to_head(player1, player2):
    if not player1 or not player2 or player1 == player2:
        return dbc.Alert("Please select two different players", color="info")

    h2h_stats = data_service.get_head_to_head_stats(player1, player2)

    if h2h_stats['matches'] == 0:
        return dbc.Alert(f"No head-to-head matches found between {player1} and {player2}", color="info")

    return dbc.Card([
        dbc.CardBody([
            html.H3(f"{player1} vs {player2}", className='text-center mb-4'),
            dbc.Row([
                dbc.Col([
                    html.H1(h2h_stats['player1_wins'], className='text-center', style={'color': '#0066cc'}),
                    html.P(f"{player1} Wins", className='text-center')
                ], width=4),
                dbc.Col([
                    html.H1(h2h_stats['halves'], className='text-center', style={'color': '#666'}),
                    html.P("Halves", className='text-center')
                ], width=4),
                dbc.Col([
                    html.H1(h2h_stats['player2_wins'], className='text-center', style={'color': '#cc0000'}),
                    html.P(f"{player2} Wins", className='text-center')
                ], width=4),
            ]),
            html.Hr(),
            html.H4(f"Total Matches: {h2h_stats['matches']}", className='text-center')
        ])
    ], className='shadow mt-4')


# ============ Player Management Callbacks ============

# Pre-fill handicap and team when a player/year is selected, and refresh after save/delete
@app.callback(
    [Output('manage-player-handicap', 'value'),
     Output('manage-player-team', 'value')],
    [Input('manage-player-dropdown', 'value'),
     Input('manage-player-year', 'value'),
     Input('btn-update-player', 'n_clicks'),
     Input('btn-delete-handicap', 'n_clicks'),
     Input('btn-delete-team', 'n_clicks')]
)
def prefill_player_handicap_and_team(player, year, update_clicks, delete_hcp_clicks, delete_team_clicks):
    if not player or not year:
        return None, None
    handicap = db_service.get_player_handicap(player, year)
    team = db_service.get_player_team_assignment(player, year)
    return handicap, team


# Add new player
@app.callback(
    Output('alert-container', 'children', allow_duplicate=True),
    Input('btn-add-player', 'n_clicks'),
    [State('new-player-name', 'value'),
     State('new-player-year', 'value'),
     State('new-player-handicap', 'value')],
    prevent_initial_call=True
)
def add_new_player(n_clicks, name, year, handicap):
    if not n_clicks:
        return None

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        return error_alert

    if not name or not year:
        return dbc.Alert("Please enter player name and year", color="danger", dismissable=True, duration=4000)

    # Add player
    db_service.add_player(name)

    # Add handicap if provided
    if handicap is not None:
        success = db_service.add_or_update_handicap(name, year, handicap)
        if success:
            data_service.invalidate_cache()
            return dbc.Alert(f"Player '{name}' added with handicap {handicap} for {year}",
                           color="success", dismissable=True, duration=4000)
        else:
            return dbc.Alert("Failed to add handicap", color="danger", dismissable=True, duration=4000)
    else:
        data_service.invalidate_cache()
        return dbc.Alert(f"Player '{name}' added (no handicap)",
                       color="success", dismissable=True, duration=4000)


# Update handicap and/or team together
@app.callback(
    Output('alert-container', 'children', allow_duplicate=True),
    Input('btn-update-player', 'n_clicks'),
    [State('manage-player-dropdown', 'value'),
     State('manage-player-year', 'value'),
     State('manage-player-handicap', 'value'),
     State('manage-player-team', 'value')],
    prevent_initial_call=True
)
def update_player_handicap_and_team(n_clicks, player, year, handicap, team):
    if not n_clicks or not player or not year:
        return dbc.Alert("Please select player and year",
                       color="danger", dismissable=True, duration=4000)

    if handicap is None and not team:
        return dbc.Alert("Enter a handicap and/or select a team to save",
                       color="danger", dismissable=True, duration=4000)

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        return error_alert

    updates = []
    failures = []

    if handicap is not None:
        if db_service.add_or_update_handicap(player, year, handicap):
            data_service.invalidate_cache()
            updates.append(f"handicap {handicap}")
        else:
            failures.append("handicap")

    if team:
        if db_service.assign_player_team(player, year, team):
            updates.append(f"{team} team")
        else:
            failures.append("team")

    if updates and not failures:
        return dbc.Alert(f"Updated {player} - {year}: {', '.join(updates)}",
                       color="success", dismissable=True, duration=4000)
    elif updates and failures:
        return dbc.Alert(f"Partially updated {player} - {year}: {', '.join(updates)} saved, {', '.join(failures)} failed",
                       color="warning", dismissable=True, duration=5000)
    return dbc.Alert("Failed to save changes", color="danger", dismissable=True, duration=4000)


# Delete handicap
@app.callback(
    Output('alert-container', 'children', allow_duplicate=True),
    Input('btn-delete-handicap', 'n_clicks'),
    [State('manage-player-dropdown', 'value'),
     State('manage-player-year', 'value')],
    prevent_initial_call=True
)
def delete_player_handicap(n_clicks, player, year):
    if not n_clicks or not player or not year:
        return dbc.Alert("Please select player and year",
                       color="danger", dismissable=True, duration=4000)

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        return error_alert

    success = db_service.delete_handicap(player, year)
    if success:
        data_service.invalidate_cache()
        return dbc.Alert(f"Handicap deleted: {player} - {year}",
                       color="success", dismissable=True, duration=4000)
    return dbc.Alert("Failed to delete handicap", color="danger", dismissable=True, duration=4000)


# Remove team assignment
@app.callback(
    Output('alert-container', 'children', allow_duplicate=True),
    Input('btn-delete-team', 'n_clicks'),
    [State('manage-player-dropdown', 'value'),
     State('manage-player-year', 'value')],
    prevent_initial_call=True
)
def delete_player_team(n_clicks, player, year):
    if not n_clicks or not player or not year:
        return dbc.Alert("Please select player and year",
                       color="danger", dismissable=True, duration=4000)

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        return error_alert

    success = db_service.delete_player_team(player, year)
    if success:
        return dbc.Alert(f"Team assignment removed: {player} - {year}",
                       color="success", dismissable=True, duration=4000)
    return dbc.Alert("Failed to remove team assignment", color="danger", dismissable=True, duration=4000)


# Display player handicaps
@app.callback(
    Output('player-handicaps-display', 'children'),
    [Input('url', 'pathname'),
     Input('btn-add-player', 'n_clicks'),
     Input('btn-update-player', 'n_clicks'),
     Input('btn-delete-handicap', 'n_clicks'),
     Input('btn-delete-team', 'n_clicks')]
)
def display_player_handicaps(pathname, add_clicks, update_clicks, delete_hcp_clicks, delete_team_clicks):
    if pathname != '/manage-players':
        return None

    players = db_service.get_all_players_with_handicaps()
    if not players:
        return dbc.Alert("No players found", color="info")

    current_year = date.today().year
    team_by_player = {
        a['name']: a['team'] for a in db_service.get_team_assignments_by_year(current_year)
    }

    cards = []
    for player in players:
        handicaps = player['handicaps']
        if handicaps:
            handicap_text = ", ".join([f"{year}: {hcp}" for year, hcp in sorted(handicaps.items(), reverse=True)])
        else:
            handicap_text = "No handicaps recorded"

        title_children = [player['name']]
        team = team_by_player.get(player['name'])
        if team:
            badge_color = '#1976d2' if team == 'Blue' else '#d32f2f'
            title_children.append(
                dbc.Badge(f"{team} Team ({current_year})", style={'backgroundColor': badge_color, 'marginLeft': '10px'})
            )

        cards.append(
            dbc.Card([
                dbc.CardBody([
                    html.H5(title_children, className='card-title'),
                    html.P(f"Handicaps: {handicap_text}", className='card-text')
                ])
            ], className='mb-2')
        )

    return html.Div(cards)


# ============ Course Management Callbacks ============

# Refresh courses table when page loads
@app.callback(
    Output('courses-table', 'data', allow_duplicate=True),
    Input('url', 'pathname'),
    prevent_initial_call=True
)
def refresh_courses_table(pathname):
    if pathname == '/manage-courses':
        courses = db_service.get_all_courses()
        return [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
    return no_update

# Populate course form when row selected
@app.callback(
    [Output('course-name', 'value'),
     Output('course-par', 'value'),
     Output('course-slope', 'value'),
     Output('course-rating', 'value')],
    Input('courses-table', 'selected_rows'),
    State('courses-table', 'data')
)
def populate_course_form(selected_rows, data):
    if not selected_rows or not data:
        return '', 72, 113, 72.0

    row = data[selected_rows[0]]
    return row['name'], row['par'], row['slope_rating'], row['course_rating']


# Add course
@app.callback(
    [Output('alert-container', 'children', allow_duplicate=True),
     Output('courses-table', 'data')],
    Input('btn-add-course', 'n_clicks'),
    [State('course-name', 'value'),
     State('course-par', 'value'),
     State('course-slope', 'value'),
     State('course-rating', 'value')],
    prevent_initial_call=True
)
def add_course(n_clicks, name, par, slope, rating):
    if not n_clicks or not name:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return dbc.Alert("Please enter course name", color="danger", dismissable=True, duration=4000), data

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return error_alert, data

    success = db_service.add_course(name, par or 72, slope or 113, rating or 72.0)
    courses = db_service.get_all_courses()
    data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
             'course_rating': c['course_rating']} for c in courses]

    if success:
        data_service.invalidate_cache()
        return dbc.Alert(f"Course '{name}' added successfully",
                       color="success", dismissable=True, duration=4000), data
    return dbc.Alert("Failed to add course (may already exist)",
                   color="danger", dismissable=True, duration=4000), data


# Update course
@app.callback(
    [Output('alert-container', 'children', allow_duplicate=True),
     Output('courses-table', 'data', allow_duplicate=True)],
    Input('btn-update-course', 'n_clicks'),
    [State('course-name', 'value'),
     State('course-par', 'value'),
     State('course-slope', 'value'),
     State('course-rating', 'value')],
    prevent_initial_call=True
)
def update_course(n_clicks, name, par, slope, rating):
    if not n_clicks or not name:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return dbc.Alert("Please enter course name", color="danger", dismissable=True, duration=4000), data

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return error_alert, data

    success = db_service.update_course(name, par or 72, slope or 113, rating or 72.0)
    courses = db_service.get_all_courses()
    data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
             'course_rating': c['course_rating']} for c in courses]

    if success:
        data_service.invalidate_cache()
        return dbc.Alert(f"Course '{name}' updated successfully",
                       color="success", dismissable=True, duration=4000), data
    return dbc.Alert("Failed to update course (may not exist)",
                   color="danger", dismissable=True, duration=4000), data


# Delete course
@app.callback(
    [Output('alert-container', 'children', allow_duplicate=True),
     Output('courses-table', 'data', allow_duplicate=True)],
    Input('btn-delete-course', 'n_clicks'),
    State('course-name', 'value'),
    prevent_initial_call=True
)
def delete_course(n_clicks, name):
    if not n_clicks or not name:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return dbc.Alert("Please enter course name", color="danger", dismissable=True, duration=4000), data

    # Check admin access
    has_access, error_alert = check_admin_access()
    if not has_access:
        courses = db_service.get_all_courses()
        data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
                 'course_rating': c['course_rating']} for c in courses]
        return error_alert, data

    success = db_service.delete_course(name)
    courses = db_service.get_all_courses()
    data = [{'name': c['name'], 'par': c['par'], 'slope_rating': c['slope_rating'],
             'course_rating': c['course_rating']} for c in courses]

    if success:
        data_service.invalidate_cache()
        return dbc.Alert(f"Course '{name}' deleted successfully",
                       color="success", dismissable=True, duration=4000), data
    return dbc.Alert("Failed to delete course (may be in use by matches)",
                   color="danger", dismissable=True, duration=4000), data


# ============ Matches Display Callbacks ============

# Filter matches by year
@app.callback(
    Output('matches-display-container', 'children'),
    Input('matches-year-filter', 'value')
)
def update_matches_display(year_filter):
    """Update matches display based on year filter"""
    # Get all matches from the database
    if year_filter == 'all':
        matches_df = db_service.get_all_matches()
    else:
        matches_df = db_service.get_matches_by_year(year_filter)
    
    if matches_df.empty:
        return dbc.Alert("No matches found", color="info", className="text-center")
    
    # Sort matches by year, day, and match number
    matches_df = matches_df.sort_values(['Year', 'Day', 'MatchNumber'])
    
    # Group matches by year and day for better organization
    years = sorted(matches_df['Year'].unique(), reverse=True)
    
    year_sections = []
    for year in years:
        year_matches = matches_df[matches_df['Year'] == year]
        days = sorted(year_matches['Day'].unique())
        
        day_sections = []
        for day in days:
            day_matches = year_matches[year_matches['Day'] == day]
            day_cards = [create_match_card(match, show_year=False) for _, match in day_matches.iterrows()]
            
            day_sections.append(
                html.Div([
                    html.H3(f"Day {day}", style={'marginBottom': '15px', 'color': '#2e7d32', 'fontSize': '1.5rem'}),
                    dbc.Row([
                        dbc.Col(card, width=12, lg=6, xl=3) for card in day_cards
                    ], className="g-3")
                ], style={'marginBottom': '30px'})
            )
        
        year_sections.append(
            html.Div([
                html.H2(f"Year {year}", style={'marginBottom': '25px', 'color': '#1b5e20', 'fontSize': '2rem', 'textAlign': 'center'}),
                html.Div(day_sections)
            ], style={'marginBottom': '50px'})
        )
    
    return html.Div(year_sections)


# ============ Teams Display Callbacks ============

# Filter teams by year
@app.callback(
    Output('teams-display-container', 'children'),
    Input('teams-year-filter', 'value')
)
def update_teams_display(year):
    """Update team roster display based on selected year"""
    if not year:
        return dbc.Alert("Select a year to view teams", color="info", className="text-center")

    assignments = db_service.get_team_assignments_by_year(year)

    if not assignments:
        return dbc.Alert(
            f"No team assignments recorded for {year} yet. Assign players to Red/Blue on the Manage Players page.",
            color="info", className="text-center"
        )

    blue_players = [p for p in assignments if p['team'] == 'Blue']
    red_players = [p for p in assignments if p['team'] == 'Red']

    return dbc.Row([
        dbc.Col([create_team_roster_card('Blue', blue_players)], width=6),
        dbc.Col([create_team_roster_card('Red', red_players)], width=6),
    ])


# ============ Edit Matches Callbacks ============

# Display matches table with edit buttons
@app.callback(
    Output('edit-matches-table-container', 'children'),
    Input('edit-match-year-filter', 'value')
)
def display_matches_for_edit(year_filter):
    if year_filter == 'all':
        matches = db_service.get_all_matches()
    else:
        matches = db_service.get_matches_by_year(year_filter)

    if matches.empty:
        return dbc.Alert("No matches found", color="info")

    # Add edit button column
    matches['Edit'] = '✏️ Edit'

    # Format team data to show both players for fourball matches with sorted names
    matches_display = matches.copy()
    matches_display['Blue Team'] = matches_display.apply(
        lambda row: " & ".join(sorted([p for p in [row['BluePlayer1'], row.get('BluePlayer2')] 
                                      if pd.notna(p) and p not in ['N/A', 'Ghost', '']])),
        axis=1
    )
    matches_display['Red Team'] = matches_display.apply(
        lambda row: " & ".join(sorted([p for p in [row['RedPlayer1'], row.get('RedPlayer2')] 
                                      if pd.notna(p) and p not in ['N/A', 'Ghost', '']])),
        axis=1
    )

    return dash_table.DataTable(
        id='matches-edit-table',
        columns=[
            {'name': 'Year', 'id': 'Year'},
            {'name': 'Day', 'id': 'Day'},
            {'name': 'Match #', 'id': 'MatchNumber'},
            {'name': 'Course', 'id': 'Course'},
            {'name': 'Type', 'id': 'MatchType'},
            {'name': 'Blue Team', 'id': 'Blue Team'},
            {'name': 'Red Team', 'id': 'Red Team'},
            {'name': 'Result', 'id': 'Result'},
            {'name': 'Score', 'id': 'Score'},
        ],
        data=matches_display[['Year', 'Day', 'MatchNumber', 'Course', 'MatchType',
                             'Blue Team', 'Red Team', 'Result', 'Score']].to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={'textAlign': 'left', 'padding': '10px'},
        style_header={'fontWeight': 'bold', 'backgroundColor': '#f8f9fa'},
        row_selectable='single',
        selected_rows=[],
        page_size=20,
        sort_action='native',
        filter_action='native'
    )


# Open edit modal
@app.callback(
    [Output('edit-match-modal', 'is_open'),
     Output('edit-match-info', 'children'),
     Output('edit-match-result', 'value'),
     Output('edit-match-score', 'value'),
     Output('selected-match-store', 'children'),
     Output('alert-container', 'children', allow_duplicate=True)],
    [Input('matches-edit-table', 'selected_rows'),
     Input('btn-close-edit-modal', 'n_clicks'),
     Input('btn-save-match-edit', 'n_clicks'),
     Input('btn-delete-match', 'n_clicks')],
    [State('matches-edit-table', 'data'),
     State('edit-match-result', 'value'),
     State('edit-match-score', 'value'),
     State('selected-match-store', 'children')],
    prevent_initial_call=True
)
def toggle_edit_modal(selected_rows, close_clicks, save_clicks, delete_clicks, table_data,
                     result_value, score_value, stored_match):
    ctx = dash.callback_context
    if not ctx.triggered:
        return False, '', '', '', '', None

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Close modal
    if trigger_id == 'btn-close-edit-modal':
        return False, '', '', '', '', None

    # Save changes
    if trigger_id == 'btn-save-match-edit' and stored_match:
        # Check admin access
        has_access, error_alert = check_admin_access()
        if not has_access:
            return False, '', '', '', '', error_alert

        import json
        match_info = json.loads(stored_match)
        success = db_service.update_match_result(
            match_info['Year'],
            match_info['Day'],
            match_info['MatchNumber'],
            result_value or '',
            score_value or ''
        )
        data_service.invalidate_cache()

        if success:
            alert = dbc.Alert(
                f"Match updated successfully! Year {match_info['Year']}, Day {match_info['Day']}, Match {match_info['MatchNumber']}",
                color="success", dismissable=True, duration=4000
            )
        else:
            alert = dbc.Alert("Failed to update match", color="danger", dismissable=True, duration=4000)

        return False, '', '', '', '', alert

    # Delete match
    if trigger_id == 'btn-delete-match' and stored_match:
        # Check admin access
        has_access, error_alert = check_admin_access()
        if not has_access:
            return False, '', '', '', '', error_alert
        import json
        match_info = json.loads(stored_match)
        success = db_service.delete_match(
            match_info['Year'],
            match_info['Day'],
            match_info['MatchNumber']
        )
        data_service.invalidate_cache()

        if success:
            alert = dbc.Alert(
                f"Match deleted successfully! Year {match_info['Year']}, Day {match_info['Day']}, Match {match_info['MatchNumber']}",
                color="warning", dismissable=True, duration=4000
            )
        else:
            alert = dbc.Alert("Failed to delete match", color="danger", dismissable=True, duration=4000)

        return False, '', '', '', '', alert

    # Open modal with selected match
    if trigger_id == 'matches-edit-table' and selected_rows and table_data:
        match = table_data[selected_rows[0]]
        import json
        stored = json.dumps({
            'Year': match['Year'],
            'Day': match['Day'],
            'MatchNumber': match['MatchNumber']
        })

        # Team display strings were already computed for the table's Blue Team/Red Team columns
        blue_team = match['Blue Team']
        red_team = match['Red Team']

        info = html.Div([
            html.P(f"Year: {match['Year']}, Day: {match['Day']}, Match: {match['MatchNumber']}"),
            html.P(f"Course: {match['Course']}"),
            html.P(f"Blue Team: {blue_team} vs Red Team: {red_team}"),
        ])

        return True, info, match.get('Result', ''), match.get('Score', ''), stored, None

    return False, '', '', '', '', None


# ============ Authentication Callbacks ============

@app.callback(
    Output('auth-store', 'data'),
    [Input('auth-check-interval', 'n_intervals'),
     Input('url', 'pathname')]
)
def update_auth_store(n, pathname):
    """Update authentication status in store"""
    # Dash callbacks have access to Flask session via flask.session
    # The session is available because Dash uses Flask under the hood
    try:
        # Try to access session directly - this works because Dash callbacks
        # are executed within Flask's request context when triggered by the client
        authenticated = is_authenticated()
        email = get_current_user_email()
        admin = is_admin()

        logger.info(f"Auth check - Authenticated: {authenticated}, Email: {email}, Admin: {admin}")

        return {
            'authenticated': authenticated,
            'email': email,
            'is_admin': admin
        }
    except Exception as e:
        logger.error(f"Error checking auth status: {e}")
        # Not authenticated or error accessing session
        return {
            'authenticated': False,
            'email': None,
            'is_admin': False
        }


@app.callback(
    Output('auth-display', 'children'),
    Input('auth-store', 'data')
)
def update_auth_display(auth_data):
    """Display authentication status"""
    if not auth_data:
        return html.Div([
            html.A('🔐 Login', href='/login', className='btn btn-success btn-sm')
        ])

    if auth_data.get('authenticated'):
        email = auth_data.get('email', 'Unknown')
        is_admin_user = auth_data.get('is_admin', False)

        badge_color = 'success' if is_admin_user else 'info'
        role_text = ' (Admin)' if is_admin_user else ' (Viewer)'

        return html.Div([
            dbc.Badge(f"👤 {email}{role_text}", color=badge_color, className='me-2'),
            html.A('🚪 Logout', href='/logout', className='btn btn-outline-danger btn-sm')
        ], style={'display': 'inline-flex', 'alignItems': 'center', 'gap': '10px'})

    return html.Div([
        html.A('🔐 Login', href='/login', className='btn btn-success btn-sm')
    ])


@app.callback(
    [Output('nav-manage-players', 'disabled'),
     Output('nav-manage-courses', 'disabled'),
     Output('nav-add-match', 'disabled'),
     Output('nav-edit-matches', 'disabled')],
    Input('auth-store', 'data')
)
def update_nav_access(auth_data):
    """Disable admin-only navigation links for non-admin users"""
    if not auth_data:
        # Disable all write operations if not authenticated
        return True, True, True, True

    # Allow if user is admin
    is_admin_user = auth_data.get('is_admin', False)
    disabled = not is_admin_user

    return disabled, disabled, disabled, disabled


# Protect write operation callbacks
def check_admin_access():
    """Helper to check if current user has admin access"""
    if not is_authenticated():
        return False, dbc.Alert('Please login to perform this action', color='warning')

    if not is_admin():
        return False, dbc.Alert('You do not have permission to perform this action. Admin access required.', color='danger')

    return True, None


# Run the app
if __name__ == '__main__':
    os.getenv('PORT', '8050')
    app.run(debug=True, port=8050)
