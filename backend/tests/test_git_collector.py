import subprocess

from app.services import git_collector


def _completed(args, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_git_repo_paths_supports_lines_and_commas():
    assert git_collector.parse_git_repo_paths(" /repo/a\n/repo/b, /repo/a ") == ["/repo/a", "/repo/b"]


def test_collect_git_activity_parses_git_log(tmp_path, monkeypatch):
    repo = tmp_path / "project-a"
    repo.mkdir()
    calls = []

    def fake_run_git(repo_path, args):
        calls.append(args)
        if args == ["rev-parse", "--show-toplevel"]:
            return _completed(args, stdout=str(repo))
        if args == ["config", "--get", "remote.origin.url"]:
            return _completed(args, stdout="git@git.garena.com:team/project-a.git\n")
        if args[0] == "log":
            assert "--author=tester@example.com" in args
            return _completed(
                args,
                stdout=(
                    "abcdef1234567890\x1fTester\x1ftester@example.com\x1f"
                    "2026-04-03T11:20:00\x1fadd git source\x1fbody text\x1e"
                ),
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(git_collector, "_run_git", fake_run_git)

    result = git_collector.collect_git_activity([str(repo)], days=2, author_filter="tester@example.com")

    assert result["date_range"] == ["2026-04-03", "2026-04-03"]
    assert result["warnings"] == []
    assert result["repositories"][0]["count"] == 1
    event = result["events"][0]
    assert event["source"] == "git"
    assert event["title"] == "project-a: add git source"
    assert event["content"] == "commit abcdef12 | author Tester <tester@example.com> | body text"
    assert event["url"] == "https://git.garena.com/team/project-a/-/commit/abcdef1234567890"
