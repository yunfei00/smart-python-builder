import pytest

from web.repositories import normalize_public_github_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/owner/repo", "https://github.com/owner/repo.git"),
        (" https://github.com/owner/repo.git ", "https://github.com/owner/repo.git"),
    ],
)
def test_normalize_public_github_url(value, expected):
    assert normalize_public_github_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://user:token@github.com/owner/repo",
        "https://github.com/owner/repo?x=1",
        "https://github.com/owner/repo/tree/main",
        "file:///tmp/repo",
    ],
)
def test_reject_non_public_github_repository_urls(value):
    with pytest.raises(ValueError):
        normalize_public_github_url(value)
