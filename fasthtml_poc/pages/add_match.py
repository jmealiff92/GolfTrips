"""Add Match form.

Port of create_add_match_page() + the related callbacks (src/app.py:713-840,
1502-1724). Per the plan: toggle_new_course_input (pure client-side visibility,
no data dependency) is replaced with a plain onchange handler instead of a
server round-trip. filter_players_by_team, toggle_player2_fields, and
auto_calculate_handicaps all key off the same input set (year, course,
match_type, 4 player selects), so they're combined into one
render_team_handicap_panel() and one HTMX fragment endpoint instead of three
independent callbacks.
"""
from datetime import date

from fasthtml.common import Div, H2, H4, P, Form, Select, Option, Input, Label, Button

from services import db_service, data_service, HandicapCalculator
from auth import check_admin_access
from layout import page


def _to_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _to_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _calculate_handicaps(year, course, match_type, blue_p1, blue_p2, red_p1, red_p2):
    """Port of auto_calculate_handicaps (src/app.py:1567-1642)."""
    if not year or not course or course == 'NEW' or not blue_p1 or not red_p1:
        return 0, 0, 0, 0

    course_info = db_service.get_course(course)
    if not course_info:
        return 0, 0, 0, 0

    try:
        blue_p1_index = db_service.get_player_handicap(blue_p1, year)
        red_p1_index = db_service.get_player_handicap(red_p1, year)
        if blue_p1_index is None or red_p1_index is None:
            return 0, 0, 0, 0

        if match_type == 'Single':
            handicaps = HandicapCalculator.calculate_match_handicaps(
                match_type='Single', handicap_index_p1=blue_p1_index, handicap_index_p2=None,
                handicap_index_p3=red_p1_index, handicap_index_p4=None,
                slope_rating=course_info['slope_rating'], par=course_info['par'],
            )
            return handicaps[0], 0, handicaps[1], 0

        elif match_type == 'Fourball':
            if not blue_p2 or not red_p2:
                return 0, 0, 0, 0
            blue_p2_index = db_service.get_player_handicap(blue_p2, year)
            red_p2_index = db_service.get_player_handicap(red_p2, year)
            if blue_p2_index is None or red_p2_index is None:
                return 0, 0, 0, 0
            handicaps = HandicapCalculator.calculate_match_handicaps(
                match_type='Fourball', handicap_index_p1=blue_p1_index, handicap_index_p2=blue_p2_index,
                handicap_index_p3=red_p1_index, handicap_index_p4=red_p2_index,
                slope_rating=course_info['slope_rating'], par=course_info['par'],
            )
            return handicaps[0], handicaps[1], handicaps[2], handicaps[3]
    except Exception:
        return 0, 0, 0, 0

    return 0, 0, 0, 0


_TEAM_PANEL_TRIGGER = (
    'change from:#input-year, change from:#input-course, change from:#input-match-type, '
    'change from:#input-blue-player1, change from:#input-blue-player2, '
    'change from:#input-red-player1, change from:#input-red-player2'
)


def _team_select(id_, name, options, selected):
    return Select(
        Option("Select player...", value="", selected=(selected is None)),
        *[Option(p, value=p, selected=(p == selected)) for p in options],
        id=id_, name=name, cls='form-select',
    )


def render_team_handicap_panel(year, course, match_type, blue_player1, blue_player2, red_player1, red_player2):
    """Port of filter_players_by_team + toggle_player2_fields + auto_calculate_handicaps combined."""
    year_int = _to_int(year)

    all_players = sorted(db_service.get_all_players())
    blue_options, red_options = all_players, all_players
    if year_int:
        assignments = db_service.get_team_assignments_by_year(year_int)
        blue_players = sorted(a['name'] for a in assignments if a['team'] == 'Blue')
        red_players = sorted(a['name'] for a in assignments if a['team'] == 'Red')
        if blue_players:
            blue_options = blue_players
        if red_players:
            red_options = red_players

    blue_player1 = blue_player1 if blue_player1 in blue_options else None
    blue_player2 = blue_player2 if blue_player2 in blue_options else None
    red_player1 = red_player1 if red_player1 in red_options else None
    red_player2 = red_player2 if red_player2 in red_options else None

    show_player2 = (match_type == 'Fourball')

    blue_p1_hcp, blue_p2_hcp, red_p1_hcp, red_p2_hcp = _calculate_handicaps(
        year_int, course, match_type, blue_player1, blue_player2, red_player1, red_player2
    )

    blocks = [
        H4("Blue Team", cls='mt-3', style='color:#0066cc'),
        Div(
            Div(Label("Player 1"), _team_select('input-blue-player1', 'blue_player1', blue_options, blue_player1), cls='col-6'),
            Div(Label("Match Handicap"), Input(id='input-blue-player1-handicap', name='blue_player1_handicap',
                                                type='number', step='0.5', value=blue_p1_hcp), cls='col-6'),
            cls='row mb-3',
        ),
    ]
    if show_player2:
        blocks.append(Div(
            Div(Label("Player 2"), _team_select('input-blue-player2', 'blue_player2', blue_options, blue_player2), cls='col-6'),
            Div(Label("Match Handicap"), Input(id='input-blue-player2-handicap', name='blue_player2_handicap',
                                                type='number', step='0.5', value=blue_p2_hcp), cls='col-6'),
            cls='row mb-3',
        ))
    else:
        blocks.append(Input(type='hidden', name='blue_player2', value=''))
        blocks.append(Input(type='hidden', name='blue_player2_handicap', value='0'))

    blocks += [
        H4("Red Team", cls='mt-3', style='color:#cc0000'),
        Div(
            Div(Label("Player 1"), _team_select('input-red-player1', 'red_player1', red_options, red_player1), cls='col-6'),
            Div(Label("Match Handicap"), Input(id='input-red-player1-handicap', name='red_player1_handicap',
                                                type='number', step='0.5', value=red_p1_hcp), cls='col-6'),
            cls='row mb-3',
        ),
    ]
    if show_player2:
        blocks.append(Div(
            Div(Label("Player 2"), _team_select('input-red-player2', 'red_player2', red_options, red_player2), cls='col-6'),
            Div(Label("Match Handicap"), Input(id='input-red-player2-handicap', name='red_player2_handicap',
                                                type='number', step='0.5', value=red_p2_hcp), cls='col-6'),
            cls='row mb-3',
        ))
    else:
        blocks.append(Input(type='hidden', name='red_player2', value=''))
        blocks.append(Input(type='hidden', name='red_player2_handicap', value='0'))

    return Div(
        *blocks,
        id='team-handicap-panel',
        hx_get='/add-match/team-panel',
        hx_trigger=_TEAM_PANEL_TRIGGER,
        hx_target='#team-handicap-panel',
        hx_swap='outerHTML',
        hx_include='closest form',
    )


def add_match_page(session: dict):
    current_year = date.today().year
    all_courses = db_service.get_all_courses()
    courses = [c['name'] for c in all_courses]
    default_course = courses[0] if courses else None

    course_select = Select(
        *[Option(c, value=c, selected=(c == default_course)) for c in courses],
        Option("+ Add New Course", value="NEW"),
        id='input-course', name='course', cls='form-select',
        onchange="document.getElementById('new-course-wrap').style.display = "
                 "(this.value === 'NEW' ? 'block' : 'none')",
    )

    form = Form(
        Div(
            Div(Label("Year"), Input(id='input-year', name='year', type='number', value=current_year,
                                      min='2018', max='2030', cls='form-control'), cls='col-4'),
            Div(Label("Day"), Input(id='input-day', name='day', type='number', value=1,
                                     min='1', max='10', cls='form-control'), cls='col-4'),
            Div(Label("Match Number"), Input(id='input-match-number', name='match_number', type='number',
                                              value=1, min='1', max='20', cls='form-control'), cls='col-4'),
            cls='row mb-3',
        ),
        Div(
            Div(
                Label("Course"), course_select,
                Div(Input(id='input-new-course', name='new_course', placeholder='Enter new course name',
                          cls='form-control mt-2'), id='new-course-wrap', style='display:none'),
                cls='col-6',
            ),
            Div(
                Label("Match Type"),
                Select(
                    Option("Single", value="Single", selected=True),
                    Option("Fourball", value="Fourball"),
                    id='input-match-type', name='match_type', cls='form-select',
                ),
                cls='col-6',
            ),
            cls='row mb-3',
        ),
        render_team_handicap_panel(current_year, default_course, 'Single', None, None, None, None),
        H4("Result (Optional)", cls='mt-3'),
        Div(
            Div(Label("Winner"), Select(
                Option("TBD", value="", selected=True), Option("Blue", value="Blue"),
                Option("Red", value="Red"), Option("Half", value="Half"),
                id='input-result', name='result', cls='form-select',
            ), cls='col-6'),
            Div(Label("Score (e.g., 3&2, A/S)"), Input(id='input-score', name='score',
                                                         placeholder='e.g., 3&2, 1UP, A/S', cls='form-control'), cls='col-6'),
            cls='row mb-3',
        ),
        Div(id='alert-container'),
        Button("Add Match", type='submit', cls='btn btn-primary btn-lg mt-3'),
        hx_post='/add-match', hx_target='#alert-container', hx_swap='innerHTML',
        cls='card card-body shadow',
    )

    return page(session, "Add Match", H2("Add New Match"), form)


def submit_add_match(session, year, day, match_number, course, new_course, match_type,
                      blue_player1, blue_player1_handicap, blue_player2, blue_player2_handicap,
                      red_player1, red_player1_handicap, red_player2, red_player2_handicap,
                      result, score):
    """Port of add_match (src/app.py:1667-1724)."""
    has_access, error_alert = check_admin_access(session)
    if not has_access:
        return error_alert

    year_i, day_i, match_number_i = _to_int(year), _to_int(day), _to_int(match_number)
    if not all([year_i, day_i, match_number_i, blue_player1, red_player1]):
        return Div(P("Please fill in all required fields"), cls='alert alert-danger')

    if db_service.check_match_exists(year_i, day_i, match_number_i):
        return Div(
            P(f"Match already exists! Year {year_i}, Day {day_i}, Match {match_number_i} is already in "
              f"the database. Please use a different match number or edit the existing match."),
            cls='alert alert-danger',
        )

    if course == 'NEW':
        if not new_course:
            return Div(P("Please enter a course name"), cls='alert alert-danger')
        course = new_course

    if match_type == 'Single':
        blue_player2 = None
        blue_player2_handicap = None
        red_player2 = None
        red_player2_handicap = None

    success = db_service.add_match(
        year=year_i, day=day_i, match_number=match_number_i,
        course=course, match_type=match_type,
        blue_player1=blue_player1, blue_player1_handicap=_to_float(blue_player1_handicap) or 0,
        blue_player2=blue_player2 or None, blue_player2_handicap=_to_float(blue_player2_handicap),
        red_player1=red_player1, red_player1_handicap=_to_float(red_player1_handicap) or 0,
        red_player2=red_player2 or None, red_player2_handicap=_to_float(red_player2_handicap),
        result=result or None, score=score or None,
    )

    if success:
        data_service.invalidate_cache()
        return Div(P(f"Match added successfully! Year {year_i}, Day {day_i}, Match {match_number_i}"),
                   cls='alert alert-success')
    else:
        return Div(P("Failed to add match. A match with this Year/Day/Match Number may already exist."),
                   cls='alert alert-danger')
