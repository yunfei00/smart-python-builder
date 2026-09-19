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


def test_explicit_ref_fetches_directly_without_default_branch_clone(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from web.repositories import clone_public_github_repository

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["git", "init"]:
            project = tmp_path / "target" / "repository"
            project.mkdir(parents=True, exist_ok=True)
            (project / ".git").mkdir()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("web.repositories.shutil.which", lambda name: "git")
    monkeypatch.setattr("web.repositories.subprocess.run", fake_run)

    result = clone_public_github_repository(
        "https://github.com/owner/repo",
        tmp_path / "target",
        "feat/example",
    )

    assert result == (tmp_path / "target" / "repository").resolve()
    assert commands[0][:2] == ["git", "init"]
    assert any(command[-2:] == ["origin", "feat/example"] for command in commands)
    assert not any("clone" in command for command in commands)
