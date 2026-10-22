"""Test doubles for the Anthropic client. No network."""
import json
from types import SimpleNamespace
from typing import Callable


def text_response(obj, stop="end_turn"):
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return SimpleNamespace(stop_reason=stop, stop_details=None, content=[SimpleNamespace(type="text", text=text)])


def search_block(*urls):
    """A web_search_tool_result block, as the API returns it after a search."""
    results = [SimpleNamespace(type="web_search_result", url=u, title=u, encrypted_content="x", page_age=None)
               for u in urls]
    return SimpleNamespace(type="web_search_tool_result", tool_use_id="srvtoolu_1", content=results)


def tool_response(name, input, stop="tool_use", before=()):
    block = SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=input)
    return SimpleNamespace(stop_reason=stop, stop_details=None, content=[*before, block])


class _Messages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kw):
        self.owner.calls.append(kw)
        if self.owner.responder is not None:
            r = self.owner.responder(kw)
        else:
            r = self.owner.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeClient:
    def __init__(self, responses: list | None = None, responder: Callable[[dict], object] | None = None):
        self.responses = list(responses or [])
        self.responder = responder
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=_Messages(self))


# ---------- canned run for the fixture export ----------

from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "export_small.csv"
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)

# title prefix -> (kind, subjects, league, team). League/team are what code should find from the tags.
CANNED_PARSES = {
    "Odell Beckham Jr Signed": ("signed", ["Odell Beckham Jr"], "NFL", "Los Angeles Rams"),
    "George Teague Signed": ("signed", ["George Teague"], "NFL", "Dallas Cowboys"),
    "Emmitt Smith and Tony Dorsett": ("signed", ["Emmitt Smith", "Tony Dorsett"], "NFL", "Dallas Cowboys"),
    "Jacob Misiorowski": ("signed", ["Jacob Misiorowski"], "MLB", "Milwaukee Brewers"),
    "Patrick Mahomes Sr": ("signed", ["Patrick Mahomes Sr"], "NFL", "Kansas City Chiefs"),
    "Christina Applegate": ("signed", ["Christina Applegate"], "", ""),
    "1981 Donruss": ("no_player", ["1981 Donruss Vintage Golf Stars"], "", ""),
    "Atlanta Braves Greats": ("signed", ["Gary Sheffield", "Dale Murphy", "Chipper Jones", "David Justice"],
                              "MLB", "Atlanta Braves"),
    "Jim Kelly": ("unsigned_player", ["Jim Kelly"], "NFL", "Buffalo Bills"),
    "Michael Irvin and Emmitt Smith": ("signed", ["Michael Irvin", "Emmitt Smith"], "NFL", "Dallas Cowboys"),
    "Tee Higgins": ("signed", ["Tee Higgins"], "NFL", "Cincinnati Bengals"),
}


def canned_parse(title: str) -> dict:
    for prefix, (kind, subjects, league, team) in CANNED_PARSES.items():
        if title.startswith(prefix):
            return {"title": title, "kind": kind, "subjects": subjects}
    raise KeyError(title)


def parse_responder(kw: dict):
    """Answers a title-parse call with the canned parse of every title it asks about."""
    items = json.loads(kw["messages"][0]["content"])
    return text_response({"results": [canned_parse(i["title"]) for i in items]})


def prepared_run(conn, fake_client_factory) -> int:
    from rsa_checkins.jobs import create_run, prepare_run
    run_id = create_run(conn, FIX, "export_small.csv", include_drafts=True)
    prepare_run(conn, fake_client_factory(responder=parse_responder), "claude-sonnet-5-5", run_id)
    return run_id
