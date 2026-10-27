"""Team and League from the product's tags (and title), by lookup - no Claude.

A tag like "Cowboys" gives Team "Dallas Cowboys" and League "NFL". The sport (from the FB/BS/BK/HK code,
a league tag, or a sport word in the type or title) rules out teams from other sports and settles shared
nicknames ("Cardinals", "Giants"). Anything unclear is left blank rather than guessed.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    city: str
    nickname: str
    league: str

    @property
    def full(self) -> str:
        return f"{self.city} {self.nickname}".strip()


def _league(league: str, rows: str) -> list[Team]:
    out = []
    for row in rows.strip().splitlines():
        city, nickname = (p.strip() for p in row.split("|"))
        out.append(Team(city, nickname, league))
    return out


# Current franchise names, matching how the store already fills Team (e.g. "Washington Commanders").
TEAMS: list[Team] = [
    *_league("NFL", """
Arizona|Cardinals
Atlanta|Falcons
Baltimore|Ravens
Buffalo|Bills
Carolina|Panthers
Chicago|Bears
Cincinnati|Bengals
Cleveland|Browns
Dallas|Cowboys
Denver|Broncos
Detroit|Lions
Green Bay|Packers
Houston|Texans
Indianapolis|Colts
Jacksonville|Jaguars
Kansas City|Chiefs
Las Vegas|Raiders
Los Angeles|Chargers
Los Angeles|Rams
Miami|Dolphins
Minnesota|Vikings
New England|Patriots
New Orleans|Saints
New York|Giants
New York|Jets
Philadelphia|Eagles
Pittsburgh|Steelers
San Francisco|49ers
Seattle|Seahawks
Tampa Bay|Buccaneers
Tennessee|Titans
Washington|Commanders
"""),
    *_league("MLB", """
Arizona|Diamondbacks
Atlanta|Braves
Baltimore|Orioles
Boston|Red Sox
Chicago|Cubs
Chicago|White Sox
Cincinnati|Reds
Cleveland|Guardians
Colorado|Rockies
Detroit|Tigers
Houston|Astros
Kansas City|Royals
Los Angeles|Angels
Los Angeles|Dodgers
Miami|Marlins
Milwaukee|Brewers
Minnesota|Twins
New York|Mets
New York|Yankees
|Athletics
Philadelphia|Phillies
Pittsburgh|Pirates
San Diego|Padres
San Francisco|Giants
Seattle|Mariners
St. Louis|Cardinals
Tampa Bay|Rays
Texas|Rangers
Toronto|Blue Jays
Washington|Nationals
"""),
    *_league("NBA", """
Atlanta|Hawks
Boston|Celtics
Brooklyn|Nets
Charlotte|Hornets
Chicago|Bulls
Cleveland|Cavaliers
Dallas|Mavericks
Denver|Nuggets
Detroit|Pistons
Golden State|Warriors
Houston|Rockets
Indiana|Pacers
Los Angeles|Clippers
Los Angeles|Lakers
Memphis|Grizzlies
Miami|Heat
Milwaukee|Bucks
Minnesota|Timberwolves
New Orleans|Pelicans
New York|Knicks
Oklahoma City|Thunder
Orlando|Magic
Philadelphia|76ers
Phoenix|Suns
Portland|Trail Blazers
Sacramento|Kings
San Antonio|Spurs
Toronto|Raptors
Utah|Jazz
Washington|Wizards
"""),
    *_league("NHL", """
Anaheim|Ducks
Boston|Bruins
Buffalo|Sabres
Calgary|Flames
Carolina|Hurricanes
Chicago|Blackhawks
Colorado|Avalanche
Columbus|Blue Jackets
Dallas|Stars
Detroit|Red Wings
Edmonton|Oilers
Florida|Panthers
Los Angeles|Kings
Minnesota|Wild
Montreal|Canadiens
Nashville|Predators
New Jersey|Devils
New York|Islanders
New York|Rangers
Ottawa|Senators
Philadelphia|Flyers
Pittsburgh|Penguins
San Jose|Sharks
Seattle|Kraken
St. Louis|Blues
Tampa Bay|Lightning
Toronto|Maple Leafs
Utah|Mammoth
Vancouver|Canucks
Vegas|Golden Knights
Washington|Capitals
Winnipeg|Jets
"""),
]

# Other spellings seen on tags -> the nickname in TEAMS.
ALIASES = {"sixers": "76ers", "niners": "49ers", "a's": "athletics", "blazers": "trail blazers", "d-backs": "diamondbacks"}

SPORT_CODE_LEAGUE = {"FB": "NFL", "BS": "MLB", "BK": "NBA", "HK": "NHL"}
LEAGUE_TAGS = {"nfl": "NFL", "mlb": "MLB", "nba": "NBA", "nhl": "NHL", "wwe": "WWE", "mls": "MLS"}
COLLEGE_TAGS = {"ncaa", "college"}

_BY_NICKNAME: dict[str, list[Team]] = {}
for _t in TEAMS:
    _BY_NICKNAME.setdefault(_t.nickname.lower(), []).append(_t)
_BY_FULL = {t.full: t for t in TEAMS}


# Sport words in the product type or title ("Autographed Football Photos", "... Baseball Jersey").
SPORT_WORD_LEAGUE = {"football": "NFL", "baseball": "MLB", "basketball": "NBA", "hockey": "NHL"}


def _named_in(team: Team, title: str) -> bool:
    """The title names this team by its city or full name (a nickname alone isn't enough)."""
    return bool(re.search(rf"\b{re.escape(team.full.lower())}\b", title)
                or (team.city and re.search(rf"\b{re.escape(team.city.lower())}\b", title)))


def match_team(tags: str, title: str, product_type: str = "") -> tuple[str, str]:
    """(team, league) for a product. Either can be "" when it can't be told for sure."""
    raw = [t.strip() for t in (tags or "").split(",") if t.strip()]
    lower = [t.lower() for t in raw]
    text = (title or "").lower()
    college = any(t in COLLEGE_TAGS for t in lower)
    sport_words = set(re.findall(r"\b(football|baseball|basketball|hockey)\b", f"{product_type} {title}".lower()))
    hints = ({SPORT_CODE_LEAGUE[t] for t in raw if t in SPORT_CODE_LEAGUE}
             | {LEAGUE_TAGS[t] for t in lower if t in LEAGUE_TAGS}
             | {SPORT_WORD_LEAGUE[w] for w in sport_words})

    def fits(team: Team) -> bool:   # never a team from another sport ("Oilers" on a football photo)
        return not hints or team.league in hints

    candidates = [t for t in dict.fromkeys(t for tag in lower for t in _BY_NICKNAME.get(ALIASES.get(tag, tag), []))
                  if fits(t)]
    if not candidates:
        candidates = [t for t in TEAMS if fits(t) and re.search(rf"\b{re.escape(t.full.lower())}\b", text)]
    if len(candidates) > 1:   # e.g. tags "Broncos" and "Ravens": the one named in the title wins
        named = [t for t in candidates if _named_in(t, text)]
        candidates = named if len(named) == 1 else candidates
    if college:   # college items: a pro team only when the title names it ("Cleveland Browns")
        candidates = [t for t in candidates if _named_in(t, text)]

    if len(candidates) == 1:
        return candidates[0].full, candidates[0].league
    if candidates:
        leagues = {t.league for t in candidates}
        return "", (leagues.pop() if len(leagues) == 1 else "")
    if college:
        return "", "NCAA"
    league_tags = {LEAGUE_TAGS[t] for t in lower if t in LEAGUE_TAGS}
    if league_tags:
        return "", (league_tags.pop() if len(league_tags) == 1 else "")
    # last resort (owner, 2026-10-22): one sport word in the title -> its league ("Baseball Jersey" -> MLB)
    title_sports = set(re.findall(r"\b(football|baseball|basketball|hockey)\b", text))
    return "", (SPORT_WORD_LEAGUE[title_sports.pop()] if len(title_sports) == 1 else "")


def team_city(full_name: str) -> str:
    """The place part of a team name ("Dallas Cowboys" -> "Dallas"), or "" if unknown."""
    team = _BY_FULL.get(full_name)
    return team.city if team else ""


def mascot_for(league: str, city: str) -> str:
    """The nickname when exactly one team in that league plays in that city ("NFL", "Pittsburgh" -> "Steelers")."""
    league, city = league.strip().lower(), city.strip().lower()
    found = [t.nickname for t in TEAMS if t.league.lower() == league and t.city.lower() == city]
    return found[0] if len(found) == 1 else ""
