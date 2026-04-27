import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote


FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
GIT_LOG_FORMAT = f"%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b%x1e"
MAX_REPOS = 20
GIT_TIMEOUT_SECONDS = 20


def parse_git_repo_paths(raw_paths: str | list[str] | None) -> list[str]:
    if raw_paths is None:
        return []
    if isinstance(raw_paths, list):
        candidates = raw_paths
    else:
        candidates = re.split(r"[\n,]", raw_paths)

    result = []
    seen = set()
    for item in candidates:
        path = str(item).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
        if len(result) >= MAX_REPOS:
            break
    return result


def _run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _resolve_repo_root(raw_path: str) -> Path:
    repo_path = Path(raw_path).expanduser()
    if not repo_path.exists():
        raise FileNotFoundError(f"仓库路径不存在：{raw_path}")
    if not repo_path.is_dir():
        raise ValueError(f"仓库路径不是目录：{raw_path}")

    result = _run_git(repo_path, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValueError(f"不是有效 Git 仓库：{raw_path}{f'（{detail}）' if detail else ''}")
    return Path(result.stdout.strip()).resolve()


def _get_remote_url(repo_root: Path) -> str | None:
    result = _run_git(repo_root, ["config", "--get", "remote.origin.url"])
    remote = result.stdout.strip()
    return remote if result.returncode == 0 and remote else None


def _commit_url(remote_url: str | None, commit_hash: str) -> str | None:
    if not remote_url:
        return None

    normalized = remote_url.strip()
    if normalized.startswith("git@"):
        host_path = normalized[4:]
        if ":" not in host_path:
            return None
        host, path = host_path.split(":", 1)
        normalized = f"https://{host}/{path}"
    elif normalized.startswith("ssh://git@"):
        host_path = normalized.removeprefix("ssh://git@")
        if "/" not in host_path:
            return None
        host, path = host_path.split("/", 1)
        normalized = f"https://{host}/{path}"
    elif normalized.startswith("http://"):
        normalized = "https://" + normalized.removeprefix("http://")

    if not normalized.startswith("https://"):
        return None

    normalized = normalized.removesuffix(".git").rstrip("/")
    if "github.com/" in normalized:
        return f"{normalized}/commit/{quote(commit_hash)}"
    return f"{normalized}/-/commit/{quote(commit_hash)}"


def _local_naive_iso(iso_timestamp: str) -> str:
    dt = datetime.fromisoformat(iso_timestamp)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


def _build_git_content(author_name: str, author_email: str, short_hash: str, body: str) -> str:
    parts = [f"commit {short_hash}", f"author {author_name} <{author_email}>"]
    cleaned_body = " ".join((body or "").split())
    if cleaned_body:
        parts.append(cleaned_body[:500])
    return " | ".join(parts)


def _parse_log_output(repo_root: Path, repo_name: str, remote_url: str | None, output: str) -> list[dict]:
    events = []
    for chunk in output.split(RECORD_SEP):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue

        fields = chunk.split(FIELD_SEP, 5)
        if len(fields) < 6:
            continue

        commit_hash, author_name, author_email, authored_at, subject, body = fields
        short_hash = commit_hash[:8]
        events.append(
            {
                "source": "git",
                "timestamp": _local_naive_iso(authored_at),
                "title": f"{repo_name}: {subject.strip() or short_hash}",
                "content": _build_git_content(author_name, author_email, short_hash, body),
                "url": _commit_url(remote_url, commit_hash),
                "repo_name": repo_name,
                "repo_path": str(repo_root),
                "commit_hash": commit_hash,
                "short_hash": short_hash,
                "author_name": author_name,
                "author_email": author_email,
                "subject": subject,
                "body": body.strip(),
            }
        )
    return events


def collect_git_activity(repo_paths: list[str], days: int = 2, author_filter: str | None = None) -> dict:
    if not repo_paths:
        raise ValueError("请先在配置页填写 Git 仓库路径")

    days = max(1, int(days or 1))
    now = datetime.now().astimezone()
    since = now - timedelta(days=days)
    author_filter = (author_filter or "").strip()

    events: list[dict] = []
    warnings: list[str] = []
    repo_results: list[dict] = []
    seen_roots: set[Path] = set()

    for raw_path in repo_paths[:MAX_REPOS]:
        try:
            repo_root = _resolve_repo_root(raw_path)
        except FileNotFoundError as exc:
            if getattr(exc, "filename", None) == "git":
                raise FileNotFoundError("未找到 git 命令，请先安装 Git")
            warnings.append(str(exc))
            repo_results.append({"path": raw_path, "status": "failed", "count": 0, "message": str(exc)})
            continue
        except Exception as exc:
            warnings.append(str(exc))
            repo_results.append({"path": raw_path, "status": "failed", "count": 0, "message": str(exc)})
            continue

        if repo_root in seen_roots:
            continue
        seen_roots.add(repo_root)

        args = [
            "log",
            "--all",
            f"--since={since.isoformat(timespec='seconds')}",
            f"--until={now.isoformat(timespec='seconds')}",
            "--date=iso-strict",
            f"--pretty=format:{GIT_LOG_FORMAT}",
        ]
        if author_filter:
            args.insert(2, f"--author={author_filter}")

        try:
            result = _run_git(repo_root, args)
        except FileNotFoundError:
            raise FileNotFoundError("未找到 git 命令，请先安装 Git")
        except subprocess.TimeoutExpired:
            message = f"Git 仓库读取超时：{repo_root}"
            warnings.append(message)
            repo_results.append({"path": str(repo_root), "status": "failed", "count": 0, "message": message})
            continue

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            message = f"Git 日志读取失败：{repo_root}{f'（{detail}）' if detail else ''}"
            warnings.append(message)
            repo_results.append({"path": str(repo_root), "status": "failed", "count": 0, "message": message})
            continue

        repo_name = repo_root.name
        repo_events = _parse_log_output(repo_root, repo_name, _get_remote_url(repo_root), result.stdout)
        events.extend(repo_events)
        repo_results.append({"path": str(repo_root), "name": repo_name, "status": "success", "count": len(repo_events)})

    events.sort(key=lambda item: item["timestamp"])
    dates = sorted({event["timestamp"][:10] for event in events})
    return {
        "events": events,
        "date_range": [dates[0], dates[-1]] if dates else [],
        "warnings": warnings,
        "repositories": repo_results,
    }
