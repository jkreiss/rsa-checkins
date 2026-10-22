from rsa_checkins.teams import TEAMS, match_team, team_city


def test_nickname_tag_gives_full_team_and_league():
    assert match_team("Cowboys, FB, imported, mini, NFL, speed", "Some Signed Helmet") == ("Dallas Cowboys", "NFL")


def test_tags_are_matched_ignoring_case():
    assert match_team("01-18, bengals, current, FB", "Tee Higgins Signed Jersey") == ("Cincinnati Bengals", "NFL")


def test_league_comes_with_the_team_without_a_league_tag():
    assert match_team("Brewers, BS, GOLD BAG", "Jacob Misiorowski Signed Jersey") == ("Milwaukee Brewers", "MLB")


def test_shared_nickname_settled_by_sport_code():
    assert match_team("Cardinals, BS", "x") == ("St. Louis Cardinals", "MLB")
    assert match_team("Cardinals, FB", "x") == ("Arizona Cardinals", "NFL")
    assert match_team("Rangers, HK", "x") == ("New York Rangers", "NHL")


def test_shared_nickname_settled_by_league_tag():
    assert match_team("Giants, NFL", "x") == ("New York Giants", "NFL")
    assert match_team("Giants, MLB", "x") == ("San Francisco Giants", "MLB")


def test_shared_nickname_with_no_hint_is_left_blank():
    assert match_team("Cardinals, Photos", "x") == ("", "")


def test_college_items_skip_the_pro_list():
    assert match_team("Cardinals, FB, NCAA", "Lamar Jackson Signed Louisville Jersey") == ("", "NCAA")
    assert match_team("College, Wolverines", "x") == ("", "NCAA")


def test_two_teams_leave_team_blank_but_keep_a_shared_league():
    assert match_team("Cowboys, Steelers, FB", "x") == ("", "NFL")
    assert match_team("Cowboys, Yankees", "x") == ("", "")


def test_full_team_name_in_title_when_no_team_tag():
    title = "Atlanta Braves Greats Sheffield, Murphy, Jones, Justice Signed Multi-Inscription Pose 2 16x20 Photo (JSA)"
    assert match_team("12-08-RSA, BS, Framed Photos, New Arrival, Photos", title) == ("Atlanta Braves", "MLB")


def test_league_tag_alone_when_no_team():
    assert match_team("BK, NBA, Photos", "Shaquille O'Neal Signed 16x20 Photo") == ("", "NBA")


def test_nothing_found():
    assert match_team("Framed Photos, New Arrival, Photos", "Christina Applegate Signed Pose 10 8x10 Photo (JSA)") == ("", "")


def test_table_has_every_team_once():
    assert len(TEAMS) == 124
    assert len({t.full for t in TEAMS}) == 124
    assert {t.league for t in TEAMS} == {"NFL", "MLB", "NBA", "NHL"}


def test_team_city():
    assert team_city("Dallas Cowboys") == "Dallas"
    assert team_city("New England Patriots") == "New England"
    assert team_city("St. Louis Cardinals") == "St. Louis"
    assert team_city("Athletics") == ""
    assert team_city("Not A Team") == ""


# ---------- cases found in the full export ----------

def test_pro_team_named_in_title_wins_over_college_tag():
    assert match_team("Browns, FB, imported, mini, NCAA, NFL, speed",
                      "Trent Richardson Signed Cleveland Browns Slate Alternate Speed Mini Football Helmet (JSA)") \
        == ("Cleveland Browns", "NFL")
    assert match_team("100+, 49ers, College, FB, jersey", "Frank Gore Signed San Francisco Red Football Jersey (Beckett)") \
        == ("San Francisco 49ers", "NFL")


def test_college_item_with_pro_nickname_not_in_title_stays_college():
    assert match_team("Cardinals, FB, NCAA", "Lamar Jackson Signed Louisville Cardinals Jersey") == ("", "NCAA")


def test_two_team_tags_settled_by_the_title():
    assert match_team("Broncos, College, FB, NFL, Ravens", "John Elway Signed Denver Broncos Throwback Speed Mini Football Helmet") \
        == ("Denver Broncos", "NFL")


def test_team_from_another_sport_is_rejected():
    # tag "Oilers" on a Houston football photo is not the Edmonton Oilers
    assert match_team("FB, import, Oilers, Photos", "Elvin Bethea Signed HOF 03 Inscription Houston Pose 1 Football 16x20 Photo (JSA)",
                      "Autographed Football Photos") == ("", "NFL")   # no team; league from "Football" in the title


def test_sport_word_in_type_beats_a_wrong_sport_code():
    assert match_team("FB, GREEN BAG, jersey, Padres", "Mason Miller Signed San Diego Black Baseball Jersey (JSA)",
                      "Autographed Baseball Jerseys") == ("San Diego Padres", "MLB")


def test_league_from_sport_word_in_title_when_nothing_else():
    assert match_team("FB, GREEN BAG, imported, jersey, V, White",
                      "Mason Miller Signed 2027 World Baseball Classic Inscription USA Olympic Baseball Jersey (JSA)",
                      "Autographed Baseball Jerseys") == ("", "MLB")
    assert match_team("jersey, Unsigned", "Steph Curry Authentic White Unsigned Basketball Jersey") == ("", "NBA")
    assert match_team("Photos", "Ric Flair Signed Pose 3 Wrestling Framed 11x14 Photo (JSA)") == ("", "")   # no league for wrestling
    assert match_team("Photos", "Bo Jackson Signed Football and Baseball 16x20 Photo") == ("", "")          # two sports: unclear


def test_league_tag_beats_the_title_word():
    assert match_team("NFL, Photos", "Deion Sanders Signed Baseball Photo") == ("", "NFL")
