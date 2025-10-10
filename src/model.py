from dataclasses import dataclass 

@dataclass
class Player:
    name: str
    handicap_index: float
    team: str

@dataclass
class Course:
    name: str
    par: int
    course_rating: float
    slope_rating: float

@dataclass
class SingleMatch:
    player1: Player
    player2: Player
    player1Handicap: int
    player2Handicap: int
    result: str
    score: str
    course: Course

@dataclass
class FourballMatch:
    player1: Player
    player2: Player
    player3: Player
    player4: Player
    player1Handicap: int
    player2Handicap: int
    player3Handicap: int
    player4Handicap: int
    result: str
    score: str
    course: Course


