"""Player Details page.

Port of create_player_details_page() + update_player_details
(src/app.py:607-709, 1728-1905). render_player_panel() is the single source of
truth for the panel's content, reused by both the full-page load and the
HTMX fragment endpoint — mirroring how the Dash callback is the one place
all this logic lives.
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from fasthtml.common import Div, H2, H3, P, Select, Option, NotStr

from services import db_service, data_service
from layout import page, data_table


def _build_points_chart(yearly_points: pd.DataFrame, player: str) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=yearly_points['Year'], y=yearly_points['Points'], name='Points', marker_color='#1e90ff'),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=yearly_points['Year'], y=yearly_points['Handicap'],
            name='Handicap Index', mode='lines+markers', marker_color='#ff8c00', connectgaps=True,
        ),
        secondary_y=True,
    )
    fig.update_layout(title=f"{player}'s Points per Year", xaxis_title="Year")
    fig.update_xaxes(tickmode='linear', dtick=1)
    fig.update_yaxes(
        title_text="Points", secondary_y=False,
        range=[0, max(yearly_points['Points']) + 1] if len(yearly_points) > 0 else None,
    )
    fig.update_yaxes(title_text="Handicap Index", secondary_y=True, showgrid=False)
    return fig


def render_player_panel(player: str):
    if not player:
        return Div(P("No player selected."), id='player-panel')

    results = data_service.build_results_per_player()
    player_results = results[results['Player'] == player]

    decided_results = player_results[player_results['Result'] != 'Pending']
    stats = decided_results['Result'].value_counts().to_dict()
    wins = stats.get('Win', 0)
    halves = stats.get('Half', 0)
    losses = stats.get('Loss', 0)
    points = wins + (halves * 0.5)
    win_pct = ((wins + (halves / 2)) / len(decided_results) * 100) if len(decided_results) > 0 else 0

    df = data_service.df
    player_matches = df[
        (df['BluePlayer1'] == player) | (df['BluePlayer2'] == player) |
        (df['RedPlayer1'] == player) | (df['RedPlayer2'] == player)
    ].copy()

    player_matches['Player_Team'] = player_matches.apply(
        lambda row: 'Blue' if player in [row['BluePlayer1'], row['BluePlayer2']] else 'Red', axis=1
    )
    player_matches['Outcome'] = player_matches.apply(
        lambda row: 'Pending' if not row['Result']
        else ('Win' if row['Result'] == row['Player_Team']
        else ('Loss' if row['Result'] != 'Half' else 'Half')), axis=1
    )

    def get_partner(row):
        if row['Player_Team'] == 'Blue':
            p1, p2 = row['BluePlayer1'], row['BluePlayer2']
        else:
            p1, p2 = row['RedPlayer1'], row['RedPlayer2']
        partner = p2 if p1 == player else p1
        if pd.isna(partner) or partner in ['N/A', 'Ghost', '']:
            return ''
        return partner

    def get_opponent(row):
        if row['Player_Team'] == 'Blue':
            o1, o2 = row['RedPlayer1'], row['RedPlayer2']
        else:
            o1, o2 = row['BluePlayer1'], row['BluePlayer2']
        opponents = [o for o in [o1, o2] if pd.notna(o) and o not in ['N/A', 'Ghost', '']]
        return ' & '.join(opponents)

    player_matches['Partner'] = player_matches.apply(get_partner, axis=1)
    player_matches['Opponent'] = player_matches.apply(get_opponent, axis=1)

    yearly_points = player_matches.groupby('Year')['Outcome'].value_counts().unstack(fill_value=0)
    yearly_points['Points'] = yearly_points.get('Win', 0) + (yearly_points.get('Half', 0) * 0.5)
    yearly_points = yearly_points.reset_index()[['Year', 'Points']]
    yearly_points['Handicap'] = yearly_points['Year'].apply(
        lambda year: db_service.get_player_handicap(player, int(year))
    )

    fig = _build_points_chart(yearly_points, player)
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False, div_id='player-points-chart')

    course_perf = data_service.get_player_course_performance(player)
    partner_stats_df = data_service.get_partner_performace(player)

    opponent_stats = []
    opponents = set()
    for _, row in player_matches.iterrows():
        if row['Player_Team'] == 'Blue':
            opp1, opp2 = row['RedPlayer1'], row['RedPlayer2']
        else:
            opp1, opp2 = row['BluePlayer1'], row['BluePlayer2']
        for opp in [opp1, opp2]:
            if pd.notna(opp) and opp not in ['N/A', 'Ghost', '']:
                opponents.add(opp)

    for opponent in opponents:
        opp_matches = player_matches[
            ((player_matches['Player_Team'] == 'Blue') &
             ((player_matches['RedPlayer1'] == opponent) | (player_matches['RedPlayer2'] == opponent))) |
            ((player_matches['Player_Team'] == 'Red') &
             ((player_matches['BluePlayer1'] == opponent) | (player_matches['BluePlayer2'] == opponent)))
        ]
        decided_opp_matches = opp_matches[opp_matches['Outcome'] != 'Pending']
        if len(decided_opp_matches) > 0:
            opp_stats = decided_opp_matches['Outcome'].value_counts().to_dict()
            opp_wins = opp_stats.get('Win', 0)
            opp_halves = opp_stats.get('Half', 0)
            opp_losses = opp_stats.get('Loss', 0)
            opp_points = opp_wins + (opp_halves * 0.5)
            ppg = opp_points / len(decided_opp_matches)
            opp_win_pct = ((opp_wins + (opp_halves * 0.5)) / len(decided_opp_matches) * 100) if len(decided_opp_matches) > 0 else 0
            opponent_stats.append({
                'Opponent': opponent, 'Matches': len(decided_opp_matches), 'Wins': opp_wins,
                'Halves': opp_halves, 'Losses': opp_losses, 'Points': opp_points,
                'PPG': round(ppg, 2), 'Win %': f"{opp_win_pct:.1f}%",
            })
    opponent_stats_df = (
        pd.DataFrame(opponent_stats).sort_values('PPG', ascending=False)
        if opponent_stats else pd.DataFrame()
    )

    match_history = player_matches[[
        'Year', 'Day', 'MatchNumber', 'Course', 'MatchType', 'Result', 'Score',
        'Player_Team', 'Partner', 'Opponent', 'Outcome',
    ]]

    return Div(
        H3(f"{player} Summary"),
        Div(
            P(f"Matches: {len(player_matches)}"),
            P(f"Wins: {wins}"), P(f"Halves: {halves}"), P(f"Losses: {losses}"),
            P(f"Points: {points:.1f}"), P(f"Win Percentage: {win_pct:.1f}%"),
        ),
        H3("Points per Year", cls='mt-4'),
        Div(NotStr(chart_html)),
        H3("Course Performance", cls='mt-4'),
        data_table(course_perf),
        H3("Fourball Partner Performance", cls='mt-4'),
        data_table(partner_stats_df),
        H3("Performance Against Opponents", cls='mt-4'),
        data_table(opponent_stats_df),
        H3("Match History", cls='mt-4'),
        data_table(match_history),
        id='player-panel',
    )


def player_dropdown(selected):
    players = sorted(data_service.players)
    return Select(
        *[Option(p, value=p, selected=(p == selected)) for p in players],
        id='player-dropdown', name='player',
        hx_get='/player-details/panel', hx_trigger='change',
        hx_target='#player-panel', hx_swap='outerHTML',
        cls='form-select mb-4', style='width: 50%',
    )


def player_details_page(session: dict):
    players = sorted(data_service.players)
    first = players[0] if players else None
    return page(
        session, "Player Details",
        H2("Player Details"),
        player_dropdown(first),
        render_player_panel(first),
    )
