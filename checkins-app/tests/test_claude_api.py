import json
from types import SimpleNamespace

import pytest

from fakes import search_block, text_response, tool_response
from rsa_checkins.claude_api import (ClaudeNoResult, ClaudeRefusal, ClaudeTruncated, call, parse_titles,
                                     research_subject)


def test_call_adds_fallback_and_raises_on_refusal(fake_client_factory):
    c = fake_client_factory([SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[])])
    with pytest.raises(ClaudeRefusal, match="cyber"):
        call(c, model="m", max_tokens=10, messages=[])
    kw = c.calls[0]
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]


def test_call_raises_on_max_tokens(fake_client_factory):
    c = fake_client_factory([text_response("{", stop="max_tokens")])
    with pytest.raises(ClaudeTruncated):
        call(c, model="m", max_tokens=10, messages=[])


def test_parse_titles_batches_and_retries_missing(fake_client_factory):
    titles = [(f"T{i} Signed Ball (JSA)", "Autographed Baseballs", "BS") for i in range(51)]
    first = text_response({"results": [{"title": t[0], "kind": "signed", "subjects": [f"P{i}"], "league": "MLB", "team": ""}
                                       for i, t in enumerate(titles[:49])]})
    retry = text_response({"results": [{"title": titles[49][0], "kind": "signed", "subjects": ["P49"], "league": "", "team": ""}]})
    second = text_response({"results": [{"title": titles[50][0], "kind": "signed", "subjects": ["P50"], "league": "", "team": ""}]})
    c = fake_client_factory([first, retry, second])
    out = parse_titles(c, "m", titles)
    assert len(out) == 51 and out[titles[50][0]].subjects == ["P50"] and out[titles[0][0]].kind == "signed"
    assert c.calls[0]["output_config"]["format"]["type"] == "json_schema"
    fields = c.calls[0]["output_config"]["format"]["schema"]["properties"]["results"]["items"]["properties"]
    assert set(fields) == {"title", "kind", "subjects"}     # team and league are worked out in code
    assert len(json.loads(c.calls[0]["messages"][0]["content"])) == 50


def test_parse_titles_gives_up_when_still_missing(fake_client_factory):
    empty = text_response({"results": []})
    c = fake_client_factory([empty, empty])
    with pytest.raises(ClaudeNoResult):
        parse_titles(c, "m", [("A Signed Ball (JSA)", "t", "")])


def test_research_subject_resumes_pause_turn_and_reads_tool(fake_client_factory):
    paused = SimpleNamespace(stop_reason="pause_turn", stop_details=None,
                             content=[SimpleNamespace(type="server_tool_use"), search_block("https://x")])
    done = tool_response("save_research", {"display_name": "Jim Kelly", "status": "retired", "sport": "Football",
                                           "teams": ["Buffalo Bills"], "current_team": None,
                                           "facts": [{"fact": "Hall of Fame 2002", "source_url": "https://x"}]})
    c = fake_client_factory([paused, done])
    r = research_subject(c, "m", "Jim Kelly", "person", ["Jim Kelly ... Unsigned Nike Football Jersey"])
    assert r.status == "retired" and r.facts[0].source_url == "https://x"
    assert c.calls[1]["messages"][-1]["role"] == "assistant" and len(c.calls[1]["messages"]) == 2
    tools = c.calls[0]["tools"]
    assert {"type": "web_search_20260209", "name": "web_search", "max_uses": 5} in tools
    assert any(t.get("name") == "save_research" and t.get("strict") for t in tools)
    assert c.calls[0]["tool_choice"] == {"type": "auto"}


def test_research_without_tool_call_raises(fake_client_factory):
    c = fake_client_factory([text_response("I could not find anything")])
    with pytest.raises(ClaudeNoResult):
        research_subject(c, "m", "Nobody", "person", [])


from rsa_checkins.claude_api import WriteItem, write_descriptions  # noqa: E402


def _item(h, kind="signed"):
    return WriteItem(h, f"{h} Signed Jersey (JSA)", "Autographed Football Jerseys", "FB", kind, "JSA", "")


def test_write_descriptions_returns_requested_handles_only(fake_client_factory):
    reply = text_response({"products": [
        {"handle": "a", "sentence1": "S", "call_to_action": "C", "note": "N", "seo_title": "A"},
        {"handle": "zzz", "sentence1": "S", "call_to_action": "C", "note": "N", "seo_title": "Z"}]})
    retry = text_response({"products": [{"handle": "b", "sentence1": "S", "call_to_action": "C", "note": "N2", "seo_title": "B"}]})
    c = fake_client_factory([reply, retry])
    out = write_descriptions(c, "m", [_item("a"), _item("b")], [], ["old note"])
    assert set(out) == {"a", "b"} and out["a"].seo_title == "A"
    assert not any(t.get("type", "").startswith("web_search") for t in c.calls[0].get("tools", []))
    assert "old note" in json.dumps(c.calls[0]["messages"])
    assert c.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_write_descriptions_gives_up_after_one_retry(fake_client_factory):
    empty = text_response({"products": []})
    c = fake_client_factory([empty, empty])
    assert write_descriptions(c, "m", [_item("a")], [], []) == {}
    assert len(c.calls) == 2


def test_write_retry_sees_notes_from_first_pass(fake_client_factory):
    first = text_response({"products": [{"handle": "a", "sentence1": "S", "call_to_action": "C", "note": "FIRST-NOTE", "seo_title": "A"}]})
    retry = text_response({"products": [{"handle": "b", "sentence1": "S", "call_to_action": "C", "note": "N2", "seo_title": "B"}]})
    c = fake_client_factory([first, retry])
    write_descriptions(c, "m", [_item("a"), _item("b")], [], [])
    assert "FIRST-NOTE" in c.calls[1]["messages"][0]["content"]


def test_call_logs_token_usage(fake_client_factory, caplog):
    r = text_response({"ok": True})
    r.usage = SimpleNamespace(input_tokens=1200, output_tokens=345, cache_read_input_tokens=1000,
                              server_tool_use=SimpleNamespace(web_search_requests=2))
    c = fake_client_factory([r])
    with caplog.at_level("INFO", logger="rsa_checkins.claude_api"):
        call(c, model="m", max_tokens=10, messages=[])
    assert "input=1200" in caplog.text and "output=345" in caplog.text and "searches=2" in caplog.text


def _save(facts, before=()):
    return tool_response("save_research", {"display_name": "Jim Kelly", "status": "retired", "sport": "Football",
                                           "teams": [], "current_team": None,
                                           "facts": [{"fact": f, "source_url": u} for f, u in facts]}, before=before)


def test_research_keeps_only_facts_sourced_from_search_results(fake_client_factory):
    reply = _save([("Hall of Fame 2002", "https://WWW.ProFootballHOF.com/players/jim-kelly/"),
                   ("Made up", "https://example.com/never-searched"),
                   ("No source", "")],
                  before=[search_block("https://www.profootballhof.com/players/jim-kelly", "https://en.wikipedia.org/wiki/Jim_Kelly")])
    r = research_subject(fake_client_factory([reply]), "m", "Jim Kelly", "person", [])
    assert [f.fact for f in r.facts] == ["Hall of Fame 2002"]


def test_research_counts_cited_urls_as_searched(fake_client_factory):
    cite = SimpleNamespace(type="web_search_result_location", url="https://bills.com/kelly", title="t", cited_text="c")
    text = SimpleNamespace(type="text", text="He played for Buffalo.", citations=[cite])
    reply = _save([("Played for Buffalo", "https://bills.com/kelly")], before=[search_block(), text])
    assert len(research_subject(fake_client_factory([reply]), "m", "Jim Kelly", "person", []).facts) == 1


def test_research_without_any_search_fails(fake_client_factory):
    reply = _save([("Hall of Fame 2002", "https://x")])
    with pytest.raises(ClaudeNoResult, match="search"):
        research_subject(fake_client_factory([reply]), "m", "Jim Kelly", "person", [])
