from system_prompts import build_system_prompt


def test_combat_entry_names_template_producer():
    prompt = build_system_prompt("greyvale_wilderness_north")
    instruction = prompt.split("- enter_mode:", 1)[1].split("\n\n", 1)[0]
    assert 'query_info(kind="creature")' in instruction
