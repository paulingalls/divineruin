import re
from copy import deepcopy
from pathlib import Path

import pytest
import test_patron_gift_content as authority
from livekit.agents.llm import ToolContext

import query_tools
from _gods_content import load_gods

ROOT = Path(__file__).resolve().parents[4]
ADR = ROOT / "docs/decisions/0001-patron-roster-sot.md"
KEYS = {"fields", "optional_fields", "recharge", "status", "mechanics_kinds", "grant"}


def parse_block(text):
    blocks = re.findall(r"^```text layer_1_gift\n(.*?)^```$", text, re.M | re.S)
    assert len(blocks) == 1, "expected one layer_1_gift block"
    values = {}
    for line in blocks[0].splitlines():
        key, separator, value = line.partition(": ")
        assert separator and key in KEYS and key not in values, "invalid block key"
        assert value.strip(), "blank block value"
        if key != "grant":
            members = value.split(", ")
            assert all(member.strip() for member in members), "blank list member"
            assert len(members) == len(set(members)), "duplicate list member"
            value = set(members)
        values[key] = value
    assert set(values) == KEYS, "missing block key"
    return values


def emitted_description():
    tools = ToolContext([query_tools.query_info]).parse_function_tools("anthropic", strict=True)
    return next(tool["description"] for tool in tools if tool["name"] == "query_info")


def grant_rule(description):
    paragraphs = re.findall(r'- kind="patron":(.*?)(?=\n\s*- kind=|\Z)', description, re.S)
    assert len(paragraphs) == 1, "missing patron paragraph"
    paragraph = " ".join(paragraphs[0].split())
    _, separator, rule = paragraph.partition("(no target_id needed). ")
    assert separator and rule, "missing patron grant rule"
    return rule


def assert_parity(text, rows, description):
    block = parse_block(text)
    expected = {
        "fields": authority.GIFT_FIELDS,
        "optional_fields": {"mechanics"},
        "recharge": authority.RECHARGES,
        "status": authority.STATUSES,
        "mechanics_kinds": authority.MECHANICS_KINDS,
        "grant": grant_rule(description),
    }
    for key, value in expected.items():
        assert block[key] == value, f"{key}: {block[key]} != {value}"
    assert rows, "empty content catalog"
    kinds = {row["layer_1_gift"]["mechanics"]["kind"] for row in rows if "mechanics" in row["layer_1_gift"]}
    assert kinds, "no mechanics-bearing gifts"
    assert block["mechanics_kinds"] == kinds, "content mechanics kinds mismatch"
    authority.validate_gifts(rows)


def assert_placeholders(text):
    sections = re.findall(r"^### Layer 2-4 placeholders[^\n]*\n(.*?)(?=^#+ |\Z)", text, re.M | re.S)
    assert len(sections) == 1, "missing placeholder section"
    assert not re.search(r"^\| `layer_1_gift`", sections[0], re.M), "Layer 1 placeholder"


def test_adr_matches_content_and_emitted_tool():
    assert_parity(ADR.read_text(), load_gods(), emitted_description())


def test_layer_1_is_not_a_placeholder():
    assert_placeholders(ADR.read_text())


@pytest.mark.parametrize("key", sorted(KEYS))
def test_parity_rejects_changed_block_values(key):
    text = ADR.read_text()
    changed = re.sub(rf"^{key}: .+$", f"{key}: wrong", text, flags=re.M)
    with pytest.raises(AssertionError, match=key):
        assert_parity(changed, load_gods(), emitted_description())


@pytest.mark.parametrize("key", ["fields", "recharge", "status", "mechanics_kinds"])
@pytest.mark.parametrize("change", ["remove", "add", "replace"])
def test_parity_rejects_list_membership_drift(key, change):
    text = ADR.read_text()
    line = re.search(rf"^{key}: (.+)$", text, re.M)
    assert line is not None
    members = line[1].split(", ")
    if change == "remove":
        members.pop()
    elif change == "add":
        members.append("unexpected")
    else:
        members[0] = "unexpected"
    text = text.replace(line[0], f"{key}: {', '.join(members)}")
    with pytest.raises(AssertionError, match=key):
        assert_parity(text, load_gods(), emitted_description())


@pytest.mark.parametrize(
    "fault", ["absent", "duplicate", "missing_key", "duplicate_key", "unknown_key", "blank", "duplicate_member"]
)
def test_parser_rejects_malformed_blocks(fault):
    text = ADR.read_text()
    block = re.search(r"^```text layer_1_gift\n.*?^```$", text, re.M | re.S)
    assert block is not None
    if fault == "absent":
        text = text.replace(block[0], "")
    elif fault == "duplicate":
        text += "\n" + block[0]
    elif fault == "missing_key":
        text = re.sub(r"^status: .*\n", "", text, flags=re.M)
    elif fault in {"duplicate_key", "unknown_key"}:
        text = text.replace(
            "fields: ", "status: wrong\nfields: " if fault == "duplicate_key" else "unknown: wrong\nfields: "
        )
    elif fault == "blank":
        text = re.sub(r"^status: .+$", "status: ", text, flags=re.M)
    else:
        text = text.replace("fields: id,", "fields: id, id,")
    with pytest.raises(AssertionError):
        parse_block(text)


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "no_mechanics",
        "third_kind",
        "authority_kind",
        "grant",
        "missing_rule",
        "missing_patron",
        "placeholder",
        "missing_heading",
    ],
)
def test_guards_reject_contract_faults(fault, monkeypatch):
    text, rows, description = ADR.read_text(), deepcopy(load_gods()), emitted_description()
    if fault == "empty":
        rows = []
    elif fault == "no_mechanics":
        for row in rows:
            row["layer_1_gift"].pop("mechanics", None)
    elif fault == "third_kind":
        rows[0]["layer_1_gift"]["mechanics"] = {"kind": "third_kind"}
    elif fault == "authority_kind":
        monkeypatch.setattr(authority, "MECHANICS_KINDS", authority.MECHANICS_KINDS | {"third_kind"})
    elif fault == "grant":
        description = description.replace("active or narrated", "awaits_rest or narrated")
    elif fault == "missing_rule":
        description = description[: description.index("Only an active")]
    elif fault == "missing_patron":
        description = description.replace('kind="patron"', 'kind="absent"')
    elif fault == "placeholder":
        text = text.replace("### Layer 2-4 placeholders", "### Layer 2-4 placeholders\n| `layer_1_gift` | null |")
    else:
        text = text.replace("### Layer 2-4 placeholders", "### Missing placeholders")
    with pytest.raises(AssertionError):
        if fault in {"placeholder", "missing_heading"}:
            assert_placeholders(text)
        else:
            assert_parity(text, rows, description)
