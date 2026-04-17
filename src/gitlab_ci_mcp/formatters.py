"""Markdown formatters for common GitLab entities.

These are used when a tool is called with ``response_format='markdown'`` to
produce a compact, context-efficient rendering that agents can summarise
easily. JSON output still contains all the raw data.
"""

from __future__ import annotations

from typing import Any

# ── Helpers ─────────────────────────────────────────────────────────────────


def _dash(v: Any) -> str:
    return "—" if v in (None, "", []) else str(v)


def _dur(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


# ── Pipeline ────────────────────────────────────────────────────────────────


def pipelines_list(d: dict) -> str:
    lines = [f"# Pipelines — `{d['project']}`", "", f"Returned **{d['count']}** pipelines.", ""]
    if not d["pipelines"]:
        lines.append("_No pipelines matched the filters._")
        return "\n".join(lines)
    lines.append("| ID | Status | Ref | Source | Duration | Created |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for p in d["pipelines"]:
        lines.append(
            f"| [{p['id']}]({p['web_url']}) | {p['status']} | `{p['ref']}` | "
            f"{_dash(p.get('source'))} | {_dur(p.get('duration'))} | {p.get('created_at') or '—'} |"
        )
    return "\n".join(lines)


def pipeline_detail(d: dict) -> str:
    return "\n".join(
        [
            f"# Pipeline [{d['id']}]({d['web_url']})",
            "",
            f"- **Status**: {d['status']}",
            f"- **Ref**: `{d['ref']}`",
            f"- **Source**: {_dash(d.get('source'))}",
            f"- **Duration**: {_dur(d.get('duration'))}",
            f"- **Queued**: {_dur(d.get('queued_duration'))}",
            f"- **Created**: {d.get('created_at') or '—'}",
            f"- **Started**: {d.get('started_at') or '—'}",
            f"- **Finished**: {d.get('finished_at') or '—'}",
        ]
    )


def pipeline_jobs(d: dict) -> str:
    lines = [f"# Jobs of pipeline `{d['pipeline_id']}`", "", f"Total jobs: **{d['jobs_count']}**.", ""]
    if not d["jobs"]:
        lines.append("_No jobs found._")
        return "\n".join(lines)
    lines.append("| ID | Name | Stage | Status | Duration |")
    lines.append("| --- | --- | --- | --- | --- |")
    for j in d["jobs"]:
        lines.append(
            f"| [{j['id']}]({j['web_url']}) | `{j['name']}` | {j['stage']} | "
            f"{j['status']} | {_dur(j.get('duration'))} |"
        )
    return "\n".join(lines)


def job_log(d: dict) -> str:
    return (
        f"# Job `{d['job_id']}` log — last {d['showing_last']} of {d['total_lines']} lines\n\n"
        f"```\n{d['log']}\n```"
    )


def pipeline_health(d: dict) -> str:
    trend_icons = {"up": "↑", "down": "↓", "flat": "="}
    trend = trend_icons.get(d["trend"], d["trend"])
    last = " ".join(d["last_10_statuses"]) if d["last_10_statuses"] else "—"
    return "\n".join(
        [
            f"# Pipeline health — `{d['project']}` · `{d['ref']}` · {d['source']}",
            "",
            "| Period | Success rate | Pipelines |",
            "| --- | --- | --- |",
            f"| Last 7d  | {d['rate_7d']:.1f}% {trend} | {d['success_7d']}/{d['total_7d']} (failed {d['failed_7d']}) |",
            f"| Last 30d | {d['rate_30d']:.1f}%   | {d['success_30d']}/{d['total_30d']} (failed {d['failed_30d']}) |",
            "",
            f"**Last 10 statuses** (newest first): {last}",
            "",
            f"_Generated at {d['generated_at']}._",
        ]
    )


# ── Schedules ───────────────────────────────────────────────────────────────


def schedules_list(d: dict) -> str:
    lines = [
        f"# CI/CD schedules — `{d['project']}`",
        "",
        f"Total: **{d['schedules_count']}** (active: **{d['active_count']}**).",
        "",
    ]
    if not d["schedules"]:
        lines.append("_No schedules configured._")
        return "\n".join(lines)
    lines.append("| ID | Active | Description | Cron | Ref | Next run |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for s in d["schedules"]:
        lines.append(
            f"| [{s['id']}]({s['web_url']}) | {'✓' if s['active'] else '✗'} | "
            f"{_dash(s['description'])} | `{s['cron']}` | `{s['ref']}` | {s.get('next_run_at') or '—'} |"
        )
    return "\n".join(lines)


# ── Branches & tags ─────────────────────────────────────────────────────────


def branches_list(d: dict) -> str:
    lines = [f"# Branches — `{d['project']}`", "", f"Returned **{d['count']}** branches.", ""]
    if not d["branches"]:
        lines.append("_No branches matched._")
        return "\n".join(lines)
    lines.append("| Name | Default | Protected | Merged | Last commit |")
    lines.append("| --- | --- | --- | --- | --- |")
    for b in d["branches"]:
        lines.append(
            f"| `{b['name']}` | {'✓' if b.get('default') else ''} | "
            f"{'✓' if b.get('protected') else ''} | {'✓' if b.get('merged') else ''} | "
            f"{_dash(b.get('commit_short_id'))} — {_dash(b.get('commit_title'))} ({_dash(b.get('committed_date'))}) |"
        )
    return "\n".join(lines)


def tags_list(d: dict) -> str:
    lines = [f"# Tags — `{d['project']}`", "", f"Returned **{d['count']}** tags (newest first).", ""]
    if not d["tags"]:
        lines.append("_No tags matched._")
        return "\n".join(lines)
    lines.append("| Name | Commit | Date | Message |")
    lines.append("| --- | --- | --- | --- |")
    for t in d["tags"]:
        msg = (t.get("message") or "").strip().splitlines()[0][:80] if t.get("message") else "—"
        lines.append(
            f"| `{t['name']}` | {_dash(t.get('commit_short_id'))} | "
            f"{_dash(t.get('committed_date'))} | {msg} |"
        )
    return "\n".join(lines)


# ── Merge requests ──────────────────────────────────────────────────────────


def mrs_list(d: dict) -> str:
    lines = [
        f"# Merge requests (state=`{d['state']}`) — `{d['project']}`",
        "",
        f"Returned **{d['count']}** MRs.",
        "",
    ]
    if not d["merge_requests"]:
        lines.append("_No merge requests matched._")
        return "\n".join(lines)
    lines.append("| IID | Title | Source → Target | Author | Status | Updated |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for m in d["merge_requests"]:
        title = (m.get("title") or "")[:80]
        lines.append(
            f"| [!{m['iid']}]({m['web_url']}) | {title} | "
            f"`{m['source_branch']}` → `{m['target_branch']}` | "
            f"{_dash(m.get('author'))} | {m['state']}/{_dash(m.get('merge_status'))} | "
            f"{m.get('updated_at') or '—'} |"
        )
    return "\n".join(lines)


def mr_detail(d: dict) -> str:
    labels = ", ".join(d.get("labels") or []) or "—"
    assignees = ", ".join(d.get("assignees") or []) or "—"
    reviewers = ", ".join(d.get("reviewers") or []) or "—"
    return "\n".join(
        [
            f"# !{d['iid']} — {d['title']}",
            f"[{d['web_url']}]({d['web_url']})",
            "",
            f"- **State**: {d['state']} / merge_status=`{_dash(d.get('merge_status'))}`"
            + (" · ⚠ conflicts" if d.get("has_conflicts") else ""),
            f"- **Branches**: `{d['source_branch']}` → `{d['target_branch']}`",
            f"- **Author**: {_dash(d.get('author'))}",
            f"- **Assignees**: {assignees}",
            f"- **Reviewers**: {reviewers}",
            f"- **Labels**: {labels}",
            f"- **Changes**: {_dash(d.get('changes_count'))} file(s)",
            f"- **Created**: {d.get('created_at') or '—'}",
            f"- **Updated**: {d.get('updated_at') or '—'}",
            f"- **Merged**: {d.get('merged_at') or '—'}",
            "",
            "## Description",
            "",
            (d.get("description") or "_(empty)_").strip(),
        ]
    )


def mr_changes(d: dict) -> str:
    lines = [
        f"# Changes of MR !{d['mr_iid']}" + (f" — {d['title']}" if d.get("title") else ""),
        "",
        f"Changed files: **{d['files_count']}**.",
        "",
    ]
    for f in d["files"]:
        flag = (
            "NEW"
            if f.get("new_file")
            else ("DEL" if f.get("deleted_file") else ("MOVE" if f.get("renamed_file") else "MOD"))
        )
        lines.append(f"## [{flag}] `{f.get('new_path') or f.get('old_path')}`")
        lines.append("")
        lines.append("```diff")
        lines.append(f.get("diff") or "")
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ── Repository ──────────────────────────────────────────────────────────────


def repo_tree(d: dict) -> str:
    lines = [
        f"# Repository tree — `{d['project']}`:{d['ref']}:{d['path']}",
        "",
        f"Entries: **{d['count']}**.",
        "",
    ]
    if not d["items"]:
        lines.append("_Empty directory or path not found._")
        return "\n".join(lines)
    for item in d["items"]:
        icon = "📁" if item["type"] == "tree" else "📄"
        lines.append(f"- {icon} `{item['path']}`")
    return "\n".join(lines)


def file_content(d: dict) -> str:
    if "error" in d:
        return f"Error reading `{d['file_path']}`@`{d['ref']}`: {d['error']}"
    marker = " (truncated)" if d.get("truncated") else ""
    return (
        f"# `{d['file_path']}` @ `{d['ref']}` — {d['total_lines']} lines, "
        f"{d['size']} bytes{marker}\n\n```\n{d['content']}\n```"
    )


def compare(d: dict) -> str:
    lines = [
        f"# Compare `{d['source']}` → `{d['target']}`",
        "",
        f"- **Commits**: {d['commits_count']}",
        f"- **Changed files**: {d['diffs_count']}",
        "",
    ]
    if d["commits"]:
        lines.append("## Commits (up to 30)")
        lines.append("")
        lines.append("| SHA | Title | Author | Date |")
        lines.append("| --- | --- | --- | --- |")
        for c in d["commits"]:
            lines.append(
                f"| `{_dash(c.get('short_id'))}` | {_dash(c.get('title'))} | "
                f"{_dash(c.get('author_name'))} | {c.get('created_at') or '—'} |"
            )
        lines.append("")
    if d["changed_files"]:
        lines.append("## Changed files")
        lines.append("")
        for f in d["changed_files"]:
            flag = (
                "NEW"
                if f.get("new_file")
                else ("DEL" if f.get("deleted_file") else "MOD")
            )
            lines.append(f"- [{flag}] `{f.get('new_path') or f.get('old_path')}`")
    return "\n".join(lines)


def project_info(d: dict) -> str:
    return "\n".join(
        [
            f"# Project `{d['path_with_namespace']}`",
            f"[{d['web_url']}]({d['web_url']})",
            "",
            f"- **ID**: {d['id']}",
            f"- **Name**: {d['name']}",
            f"- **Default branch**: `{d['default_branch']}`",
            f"- **Visibility**: {_dash(d.get('visibility'))}",
            f"- **Created**: {d.get('created_at') or '—'}",
            f"- **Last activity**: {d.get('last_activity_at') or '—'}",
            f"- **Open issues**: {_dash(d.get('open_issues_count'))}",
            f"- **Forks**: {_dash(d.get('forks_count'))}",
            f"- **Stars**: {_dash(d.get('star_count'))}",
        ]
    )
