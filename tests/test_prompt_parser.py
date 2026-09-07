import pytest

from prompt_timeline import PromptTimelineError, parse_timeline_prompt, parse_multi_part_prompt


def test_timestamp_formats_are_parsed():
    operations = parse_timeline_prompt("blur from 01:02 to 01:05")
    assert operations[0].start_time == 62
    assert operations[0].end_time == 65


def test_invalid_range_is_rejected():
    with pytest.raises(PromptTimelineError):
        parse_timeline_prompt("blur from 5 to 2")


def test_multi_part_scope_is_preserved():
    result = parse_multi_part_prompt(
        "Part 1: blur from 0 to 2; Part 2: grayscale from 0 to 2; Part 3: mirror from 0 to 1",
        3,
    )
    assert [item.effect for item in result[0]] == ["blur"]
    assert [item.effect for item in result[1]] == ["grayscale"]
    assert [item.effect for item in result[2]] == ["mirror"]
