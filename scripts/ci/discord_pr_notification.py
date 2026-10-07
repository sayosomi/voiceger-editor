"""Discord notifications for pull-request CI and merge lifecycle events."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

UNAVAILABLE = "unavailable"
MAX_DISCORD_MESSAGE_LENGTH = 2000
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
FAILURE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}


def _normalize(value: Any) -> str:
    if not isinstance(value, (str, int)):
        return ""
    return " ".join(str(value).split())


def _display(value: Any, limit: int) -> str:
    normalized = _normalize(value)
    if not normalized:
        return UNAVAILABLE
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)] + "…"


def _truncate(value: str, limit: int = MAX_DISCORD_MESSAGE_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def _is_failure(conclusion: Any) -> bool:
    return isinstance(conclusion, str) and conclusion in FAILURE_CONCLUSIONS


def select_failed_job(jobs: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    failed = [job for job in jobs if _is_failure(job.get("conclusion"))]
    return next((job for job in failed if job.get("name") != "CI"), failed[0] if failed else None)


def select_failed_step(job: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not job:
        return None
    steps = job.get("steps")
    if not isinstance(steps, list):
        return None
    return next(
        (step for step in steps if isinstance(step, dict) and _is_failure(step.get("conclusion"))),
        None,
    )


def build_merge_content(*, repository: str, number: Any, title: Any, url: Any) -> str:
    return _truncate(
        "\n".join(
            [
                f"✅ [{_display(repository, 180)}] PR #{_display(number, 32)} merged",
                _display(title, 400),
                _display(url, 350),
            ]
        )
    )


def build_ci_failure_content(
    *,
    repository: str,
    pr_number: Any,
    title: Any,
    run: Dict[str, Any],
    job: Optional[Dict[str, Any]],
    step: Optional[Dict[str, Any]],
) -> str:
    return _truncate(
        "\n".join(
            [
                f"⚠️ [{_display(repository, 180)}] CI {_display(run.get('conclusion'), 40)} — PR #{_display(pr_number, 32)}",
                _display(title, 400),
                f"head SHA: {_display(run.get('head_sha'), 64)}",
                f"run attempt: {_display(run.get('run_attempt'), 32)}",
                f"Actions run: {_display(run.get('html_url'), 350)}",
                f"failed job: {_display(job.get('name') if job else None, 160)}",
                f"failed step: {_display(step.get('name') if step else None, 160)}",
            ]
        )
    )


def build_out_of_date_content(
    *,
    repository: str,
    number: Any,
    title: Any,
    url: Any,
    main_sha: Any,
    head_sha: Any,
) -> str:
    return _truncate(
        "\n".join(
            [
                f"⚠️ [{_display(repository, 180)}] PR #{_display(number, 32)} out of date — latest main integration required",
                _display(title, 400),
                f"PR URL: {_display(url, 350)}",
                f"main SHA: {_display(main_sha, 64)}",
                f"PR head SHA: {_display(head_sha, 64)}",
            ]
        )
    )


def _request_json(url: str, *, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "voiceger-editor-ci-notifier",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _api_url(repository: str, path: str) -> str:
    quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in repository.split("/", 1))
    return f"https://api.github.com/repos/{quoted_repo}{path}"


def _post_discord(webhook_url: str, content: str) -> None:
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is required")
    payload = json.dumps(
        {"content": content, "allowed_mentions": {"parse": []}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "voiceger-editor-ci-notifier"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Discord webhook returned HTTP status {response.status}")


def _event() -> Dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH is required")
    with Path(event_path).open("r", encoding="utf-8") as event_file:
        value = json.load(event_file)
    if not isinstance(value, dict):
        raise RuntimeError("GitHub event payload must be an object")
    return value


def _environment() -> Tuple[str, str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not repository:
        raise RuntimeError("GITHUB_REPOSITORY is required")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    return repository, token, webhook_url


def _compare_behind_by(*, repository: str, main_sha: str, head_sha: str, token: str) -> int:
    if not SHA_PATTERN.fullmatch(main_sha) or not SHA_PATTERN.fullmatch(head_sha):
        raise RuntimeError("comparison requires valid commit SHAs")
    payload = _request_json(
        _api_url(repository, f"/compare/{main_sha}...{head_sha}"),
        token=token,
    )
    behind_by = payload.get("behind_by") if isinstance(payload, dict) else None
    if not isinstance(behind_by, int) or behind_by < 0:
        raise RuntimeError("GitHub compare API returned invalid behind_by")
    return behind_by


def _list_open_main_pull_requests(*, repository: str, token: str) -> List[Dict[str, Any]]:
    pull_requests: List[Dict[str, Any]] = []
    for page in range(1, 101):
        payload = _request_json(
            _api_url(repository, f"/pulls?state=open&base=main&per_page=100&page={page}"),
            token=token,
        )
        if not isinstance(payload, list):
            raise RuntimeError("GitHub pulls API returned invalid data")
        page_items = [item for item in payload if isinstance(item, dict)]
        pull_requests.extend(page_items)
        if len(payload) < 100:
            return pull_requests
    raise RuntimeError("GitHub pulls API exceeded pagination safety limit")


def _eligible_pull_request(pull_request: Dict[str, Any]) -> bool:
    return (
        pull_request.get("state") == "open"
        and pull_request.get("draft") is False
        and isinstance(pull_request.get("number"), int)
        and pull_request.get("base", {}).get("ref") == "main"
        and bool(SHA_PATTERN.fullmatch(str(pull_request.get("head", {}).get("sha", ""))))
    )


def notify_merge() -> None:
    _repository, _token, webhook_url = _environment()
    content = build_merge_content(
        repository=os.environ.get("REPOSITORY_NAME", ""),
        number=os.environ.get("PR_NUMBER", ""),
        title=os.environ.get("PR_TITLE", ""),
        url=os.environ.get("PR_URL", ""),
    )
    _post_discord(webhook_url, content)


def notify_ci_failure() -> None:
    repository, token, webhook_url = _environment()
    event = _event()
    run = event.get("workflow_run")
    if not isinstance(run, dict) or run.get("event") != "pull_request":
        raise RuntimeError("Expected a pull-request workflow_run event")
    if run.get("conclusion") == "success":
        return
    if not _is_failure(run.get("conclusion")):
        return

    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list) or not pull_requests:
        return
    if len(pull_requests) != 1 or not isinstance(pull_requests[0], dict):
        raise RuntimeError("Expected exactly one pull request for the CI workflow run")
    pr_number = pull_requests[0].get("number")
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise RuntimeError("CI workflow run does not identify a valid pull request")

    pr = _request_json(_api_url(repository, f"/pulls/{pr_number}"), token=token)
    jobs_payload = _request_json(
        _api_url(repository, f"/actions/runs/{run.get('id')}/jobs?per_page=100"),
        token=token,
    )
    jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, dict) else None
    job = select_failed_job(jobs if isinstance(jobs, list) else [])
    step = select_failed_step(job)
    content = build_ci_failure_content(
        repository=repository,
        pr_number=pr_number,
        title=pr.get("title") if isinstance(pr, dict) else None,
        run=run,
        job=job,
        step=step,
    )
    _post_discord(webhook_url, content)


def notify_main_push() -> None:
    repository, token, webhook_url = _environment()
    event = _event()
    if event.get("ref") != "refs/heads/main":
        raise RuntimeError("Expected a push to main")
    before = event.get("before")
    after = event.get("after")
    if not isinstance(before, str) or not isinstance(after, str):
        raise RuntimeError("Push event is missing main SHAs")
    if not SHA_PATTERN.fullmatch(before) or not SHA_PATTERN.fullmatch(after):
        raise RuntimeError("Push event contains invalid main SHAs")

    for pull_request in _list_open_main_pull_requests(repository=repository, token=token):
        if not _eligible_pull_request(pull_request):
            continue
        head_sha = str(pull_request["head"]["sha"])
        if _compare_behind_by(
            repository=repository, main_sha=before, head_sha=head_sha, token=token
        ) != 0:
            continue
        if _compare_behind_by(
            repository=repository, main_sha=after, head_sha=head_sha, token=token
        ) <= 0:
            continue
        _post_discord(
            webhook_url,
            build_out_of_date_content(
                repository=repository,
                number=pull_request.get("number"),
                title=pull_request.get("title"),
                url=pull_request.get("html_url"),
                main_sha=after,
                head_sha=head_sha,
            ),
        )


def notify_pr_lifecycle() -> None:
    repository, token, webhook_url = _environment()
    event = _event()
    if event.get("action") not in {"opened", "reopened", "ready_for_review"}:
        raise RuntimeError("Expected an actionable pull_request_target event")
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict) or not _eligible_pull_request(pull_request):
        return

    main_sha = pull_request.get("base", {}).get("sha")
    head_sha = pull_request.get("head", {}).get("sha")
    if not isinstance(main_sha, str) or not isinstance(head_sha, str):
        raise RuntimeError("Pull request event is missing base/head SHAs")
    if _compare_behind_by(
        repository=repository, main_sha=main_sha, head_sha=head_sha, token=token
    ) <= 0:
        return
    _post_discord(
        webhook_url,
        build_out_of_date_content(
            repository=repository,
            number=pull_request.get("number"),
            title=pull_request.get("title"),
            url=pull_request.get("html_url"),
            main_sha=main_sha,
            head_sha=head_sha,
        ),
    )


def main(argv: Optional[List[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        raise RuntimeError(
            "Usage: discord_pr_notification.py <merge|ci-failure|main-push|pr-lifecycle>"
        )
    mode = arguments[0]
    if mode == "merge":
        notify_merge()
    elif mode == "ci-failure":
        notify_ci_failure()
    elif mode == "main-push":
        notify_main_push()
    elif mode == "pr-lifecycle":
        notify_pr_lifecycle()
    else:
        raise RuntimeError(
            "Usage: discord_pr_notification.py <merge|ci-failure|main-push|pr-lifecycle>"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
