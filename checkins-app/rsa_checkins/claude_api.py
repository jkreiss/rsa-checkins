"""Every call to Claude goes through this module."""
import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import anthropic

from . import rules

FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
MAX_TOKENS = 16000
PARSE_BATCH = 50
MAX_PAUSE_CONTINUATIONS = 5

log = logging.getLogger(__name__)


class ClaudeError(Exception):
    pass


class ClaudeRefusal(ClaudeError):
    pass


class ClaudeTruncated(ClaudeError):
    pass


class ClaudeNoResult(ClaudeError):
    pass


# Errors that count as a failed attempt: our own checks, and API errors left after the SDK's retries.
WORK_ERRORS = (ClaudeError, anthropic.APIError)


def make_client(api_key: str | None = None) -> anthropic.Anthropic:
    # Worst case (timeout x attempts) stays within the 15-minute work claim.
    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=300)


def call(client, **kwargs):
    response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    _log_usage(kwargs.get("model"), getattr(response, "usage", None))
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise ClaudeRefusal(f"Claude declined the request (category: {category or 'unknown'})")
    if response.stop_reason == "max_tokens":
        raise ClaudeTruncated("Claude's reply was cut off (too long)")
    return response


def _log_usage(model, usage) -> None:
    if usage is None:
        return
    tool = getattr(usage, "server_tool_use", None)
    log.info("tokens model=%s input=%s cache_read=%s output=%s searches=%s", model,
             getattr(usage, "input_tokens", 0), getattr(usage, "cache_read_input_tokens", 0) or 0,
             getattr(usage, "output_tokens", 0), getattr(tool, "web_search_requests", 0) if tool else 0)


def _json_text(response) -> dict:
    try:
        text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
        return json.loads(text)
    except (StopIteration, json.JSONDecodeError) as e:
        raise ClaudeNoResult(f"Claude's reply wasn't valid JSON: {e}") from e


def _schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


# ---------- title parsing ----------

@dataclass(frozen=True)
class TitleParse:
    kind: Literal["signed", "unsigned_player", "no_player"]
    subjects: list[str]


_PARSE_SCHEMA = _schema({
    "results": {"type": "array", "items": _schema({
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": ["signed", "unsigned_player", "no_player"]},
        "subjects": {"type": "array", "items": {"type": "string"}},
    })},
})


def _parse_batch(client, model: str, items: list[tuple[str, str, str]]) -> dict[str, TitleParse]:
    payload = [{"title": t, "product_type": ty, "tags": tg} for t, ty, tg in items]
    response = call(
        client, model=model, max_tokens=MAX_TOKENS, system=rules.TITLE_PARSE_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": {"type": "json_schema", "schema": _PARSE_SCHEMA}},
    )
    wanted = {t for t, _, _ in items}
    out = {}
    for r in _json_text(response).get("results", []):
        if r.get("title") in wanted:
            out[r["title"]] = TitleParse(r["kind"], [s.strip() for s in r["subjects"] if s.strip()])
    return out


def parse_titles(client, model: str, items: list[tuple[str, str, str]]) -> dict[str, TitleParse]:
    out: dict[str, TitleParse] = {}
    for i in range(0, len(items), PARSE_BATCH):
        batch = items[i:i + PARSE_BATCH]
        got = _parse_batch(client, model, batch)
        missing = [it for it in batch if it[0] not in got]
        if missing:
            got.update(_parse_batch(client, model, missing))
            still = [it[0] for it in batch if it[0] not in got]
            if still:
                raise ClaudeNoResult(f"Couldn't read {len(still)} title(s), e.g. {still[0]!r}")
        out.update(got)
    return out


# ---------- research ----------

@dataclass(frozen=True)
class Fact:
    fact: str
    source_url: str


@dataclass(frozen=True)
class Research:
    display_name: str
    status: Literal["active", "retired", "unknown"]
    sport: str
    teams: list[str]
    current_team: str | None
    facts: list[Fact]


_SAVE_RESEARCH_TOOL = {
    "name": "save_research",
    "description": "Save the verified research about this subject. Call exactly once, at the end.",
    "strict": True,
    "input_schema": _schema({
        "display_name": {"type": "string", "description": "Full correct name"},
        "status": {"type": "string", "enum": ["active", "retired", "unknown"]},
        "sport": {"type": "string", "description": "Sport or field, e.g. Football, Baseball, Entertainment"},
        "teams": {"type": "array", "items": {"type": "string"}},
        "current_team": {"type": ["string", "null"]},
        "facts": {"type": "array", "items": _schema({
            "fact": {"type": "string"},
            "source_url": {"type": "string"},
        })},
    }),
}


def normalize_url(url: str) -> str:
    """Compare URLs loosely: case of scheme/host, "www.", fragment and a trailing slash don't matter."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), parts.query, ""))


def _searched_urls(content) -> tuple[int, set[str]]:
    """Result blocks seen, and every URL that came back from a search or was cited."""
    searches, urls = 0, set()
    for block in content:
        btype = getattr(block, "type", "")
        if btype == "web_search_tool_result":
            searches += 1
            results = getattr(block, "content", None)
            if isinstance(results, list):
                urls.update(normalize_url(r.url) for r in results if getattr(r, "url", ""))
        for c in getattr(block, "citations", None) or []:
            if getattr(c, "url", ""):
                urls.add(normalize_url(c.url))
    return searches, urls


def research_subject(client, model: str, name: str, kind: str, example_titles: list[str]) -> Research:
    examples = "\n".join(f"- {t}" for t in example_titles) or "- (none)"
    user = {"role": "user", "content": f"Subject: {name}\nKind: {kind}\nProducts we sell for this subject:\n{examples}"}
    messages = [user]
    searches, urls = 0, set()
    for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
        response = call(
            client, model=model, max_tokens=MAX_TOKENS, system=rules.RESEARCH_PROMPT, messages=messages,
            tools=[WEB_SEARCH_TOOL, _SAVE_RESEARCH_TOOL], tool_choice={"type": "auto"},
        )
        n, found = _searched_urls(response.content)
        searches, urls = searches + n, urls | found
        for block in response.content:
            if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == "save_research":
                if searches == 0:
                    raise ClaudeNoResult(f"Claude saved research for {name} without doing a web search")
                data = block.input if isinstance(block.input, dict) else json.loads(block.input)
                facts = [Fact(f["fact"].strip(), f["source_url"].strip()) for f in data["facts"] if f["fact"].strip()]
                # Spec: only facts confirmed in web search results may be used.
                kept = [f for f in facts if f.source_url and normalize_url(f.source_url) in urls]
                if len(kept) < len(facts):
                    log.info("research %s: dropped %d of %d fact(s) whose source wasn't in the search results",
                             name, len(facts) - len(kept), len(facts))
                return Research(
                    display_name=data["display_name"].strip() or name,
                    status=data["status"],
                    sport=data["sport"],
                    teams=list(data["teams"]),
                    current_team=data["current_team"],
                    facts=kept,
                )
        if response.stop_reason != "pause_turn":
            break
        # Re-send the paused turn so the server continues it (its content is kept as-is).
        messages = [user, {"role": "assistant", "content": response.content}]
    raise ClaudeNoResult(f"Claude didn't save any research for {name}")


# ---------- writing ----------

@dataclass(frozen=True)
class WriteItem:
    handle: str
    title: str
    product_type: str
    tags: str
    kind: str
    authenticator: str
    team: str
    opening: str = ""      # signed items: the first-sentence pattern to follow (rules.SIGNED_OPENINGS)


@dataclass(frozen=True)
class SubjectFacts:
    name: str
    kind: str
    status: str
    sport: str
    teams: list[str]
    current_team: str | None
    facts: list[Fact]


@dataclass(frozen=True)
class WrittenParts:
    sentence1: str
    call_to_action: str
    note: str
    seo_title: str


_WRITE_SCHEMA = _schema({
    "products": {"type": "array", "items": _schema({
        "handle": {"type": "string"},
        "sentence1": {"type": "string"},
        "call_to_action": {"type": "string"},
        "note": {"type": "string"},
        "seo_title": {"type": "string"},
    })},
})


def _write_batch(client, model, items, subjects, previous_notes) -> dict[str, WrittenParts]:
    payload = {
        "products": [asdict(i) for i in items],
        "subjects": [asdict(s) for s in subjects],
        "previous_notes": previous_notes,
    }
    response = call(
        client, model=model, max_tokens=MAX_TOKENS, system=rules.WRITE_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
        output_config={"format": {"type": "json_schema", "schema": _WRITE_SCHEMA}},
    )
    wanted = {i.handle for i in items}
    out = {}
    for p in _json_text(response).get("products", []):
        if p.get("handle") in wanted and p["sentence1"].strip() and p["note"].strip():
            out[p["handle"]] = WrittenParts(p["sentence1"].strip(), p["call_to_action"].strip(),
                                            p["note"].strip(), p["seo_title"].strip())
    return out


def write_descriptions(client, model: str, items: list[WriteItem], subjects: list[SubjectFacts],
                       previous_notes: list[str]) -> dict[str, WrittenParts]:
    out = _write_batch(client, model, items, subjects, previous_notes)
    missing = [i for i in items if i.handle not in out]
    if missing:
        notes = previous_notes + [p.note for p in out.values()]
        out.update(_write_batch(client, model, missing, subjects, notes))
    return out
