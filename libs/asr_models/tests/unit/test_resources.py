"""The word lists are stored via Git LFS: a checkout without LFS leaves pointer
files in place, which the consumers would read as three-word lexicons."""

from importlib import resources

import pytest

LISTS = {"freq_de.txt": 40_000, "freq_en.txt": 40_000, "freq_uk.txt": 40_000, "names.txt": 3_000}


@pytest.mark.parametrize(("name", "at_least"), sorted(LISTS.items()))
def test_word_list_is_real_content_not_an_lfs_pointer(name: str, at_least: int) -> None:
    text = resources.files("asr_models").joinpath("resources", name).read_text("utf-8")
    assert not text.startswith("version https://git-lfs"), (
        f"{name} is an LFS pointer; run `git lfs pull`"
    )
    assert sum(1 for line in text.splitlines() if line.strip()) >= at_least
