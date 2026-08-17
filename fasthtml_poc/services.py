"""Shared service singletons for the FastHTML POC, reusing src/ as-is.

Mirrors src/app.py's own sys.path/import/init pattern so this POC talks to the
exact same database and business-logic layer as the Dash app, unmodified.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_REPO_ROOT, '.env'))

from src.db_service import get_database_service
from src.data_service import DataService
from src.handicap_calculator import HandicapCalculator

db_path = os.path.join(_REPO_ROOT, 'data', 'golf_trips.db')
db_service = get_database_service(db_path)
data_service = DataService(db_service)
