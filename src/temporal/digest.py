"""Render digests from the temporal store.

Output formats: markdown (default), html, json, slack_blocks.

Group commits by intent, then chronologically. Highlight high-risk commits.

Usage:
    store = TemporalStore("context/temporal/commits.sqlite")
    md = render_daily(store, date(2026, 5, 8), fmt="markdown")
    html = render_daily(store, date(2026, 5, 8), fmt="html")
    slack = render_daily(store, date(2026, 5, 8), fmt="slack_blocks")
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def render_daily(
    store: Any,
    day: date,
    fmt: str = "markdown",
) -> str:
    """Render a daily digest for the given date.

    Args:
        store: TemporalStore instance with enriched commits.
        day: The date to render.
        fmt: Output format — "markdown", "html", "json", "slack_blocks".

    Returns:
        Rendered digest string (or JSON for json format).
    """
    # Get all enriched commits for this day
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    # Query all enriched commits and filter by date
    all_enriched = store.enriched_commits(limit=1000)
    day_commits = []
    for commit in all_enriched:
        try:
            commit_date = datetime.fromisoformat(commit["date"])
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)
            if day_start <= commit_date < day_end:
                day_commits.append(commit)
        except (ValueError, KeyError):
            continue

    # Sort by date (oldest first)
    day_commits.sort(key=lambda c: c.get("date", ""))

    if not day_commits:
        if fmt == "markdown":
            return f"# Changelog — {day.isoformat()}\n\nNo commits."
        elif fmt == "html":
            return _html_empty(day)
        elif fmt == "json":
            return _json_empty(day)
        elif fmt == "slack_blocks":
            return _slack_empty(day)

    # Group by intent
    grouped: Dict[str, List[Dict]] = {}
    for commit in day_commits:
        intent = commit.get("intent", "unknown")
        if intent not in grouped:
            grouped[intent] = []
        grouped[intent].append(commit)

    # Count high-risk commits
    high_risk = [c for c in day_commits if c.get("risk_score", 0) >= 0.5]

    if fmt == "markdown":
        return _render_markdown(day, day_commits, grouped, high_risk)
    elif fmt == "html":
        return _render_html(day, day_commits, grouped, high_risk)
    elif fmt == "json":
        return _render_json(day, day_commits, grouped, high_risk)
    elif fmt == "slack_blocks":
        return _render_slack(day, day_commits, grouped, high_risk)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def render_weekly(
    store: Any,
    week_ending: date,
    fmt: str = "markdown",
) -> str:
    """Render a weekly digest ending on the given date (Monday).

    Args:
        store: TemporalStore instance.
        week_ending: The Monday date that ends the week.
        fmt: Output format.

    Returns:
        Rendered weekly digest.
    """
    week_start = week_ending - timedelta(days=6)  # Sunday

    # Get all enriched commits in the week range
    all_enriched = store.enriched_commits(limit=1000)
    week_commits = []
    for commit in all_enriched:
        try:
            commit_date = datetime.fromisoformat(commit["date"])
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)
            week_start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
            week_end_dt = datetime(week_ending.year, week_ending.month, week_ending.day, 23, 59, 59, tzinfo=timezone.utc)
            if week_start_dt <= commit_date <= week_end_dt:
                week_commits.append(commit)
        except (ValueError, KeyError):
            continue

    week_commits.sort(key=lambda c: c.get("date", ""))

    if not week_commits:
        return f"# Weekly Changelog — {week_start.isoformat()} to {week_ending.isoformat()}\n\nNo commits."

    # Group by intent
    grouped: Dict[str, List[Dict]] = {}
    for commit in week_commits:
        intent = commit.get("intent", "unknown")
        if intent not in grouped:
            grouped[intent] = []
        grouped[intent].append(commit)

    high_risk = [c for c in week_commits if c.get("risk_score", 0) >= 0.5]

    if fmt == "markdown":
        return _render_markdown_weekly(week_start, week_ending, week_commits, grouped, high_risk)
    elif fmt == "html":
        return _render_html_weekly(week_start, week_ending, week_commits, grouped, high_risk)
    elif fmt == "json":
        return _render_json_weekly(week_start, week_ending, week_commits, grouped, high_risk)
    elif fmt == "slack_blocks":
        return _render_slack_weekly(week_start, week_ending, week_commits, grouped, high_risk)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def render_module(
    store: Any,
    module: str,
    days: int = 7,
    fmt: str = "markdown",
) -> str:
    """Render a per-module digest for the last N days.

    Args:
        store: TemporalStore instance.
        module: Module path (e.g. "src/auth").
        days: Number of days to look back.
        fmt: Output format.

    Returns:
        Rendered module digest.
    """
    commits = store.commits_for_module(module, limit=100)
    commits.sort(key=lambda c: c.get("date", ""))

    if not commits:
        if fmt == "markdown":
            return f"# Changelog — Module: {module}\n\nNo commits in the last {days} days."
        elif fmt == "html":
            return _html_empty_module(module, days)
        elif fmt == "json":
            return _json_empty_module(module, days)
        elif fmt == "slack_blocks":
            return _slack_empty_module(module, days)

    grouped: Dict[str, List[Dict]] = {}
    for commit in commits:
        intent = commit.get("intent", "unknown")
        if intent not in grouped:
            grouped[intent] = []
        grouped[intent].append(commit)

    high_risk = [c for c in commits if c.get("risk_score", 0) >= 0.5]

    if fmt == "markdown":
        return _render_markdown_module(module, commits, grouped, high_risk)
    elif fmt == "html":
        return _render_html_module(module, commits, grouped, high_risk)
    elif fmt == "json":
        return _render_json_module(module, commits, grouped, high_risk)
    elif fmt == "slack_blocks":
        return _render_slack_module(module, commits, grouped, high_risk)
    else:
        raise ValueError(f"Unknown format: {fmt}")


# ── Markdown rendering ────────────────────────────────────────────

INTENT_LABELS = {
    "feature": "Features",
    "fix": "Fixes",
    "refactor": "Refactors",
    "chore": "Chore",
    "docs": "Documentation",
    "test": "Tests",
    "unknown": "Unknown",
}


def _render_markdown(
    day: date,
    commits: List[Dict],
    grouped: Dict[str, List[Dict]],
    high_risk: List[Dict],
) -> str:
    """Render a daily markdown digest."""
    lines = [
        f"# Changelog — {day.isoformat()}",
        "",
        f"**{len(commits)} commits**" if len(commits) != 1 else "**1 commit**",
    ]

    # Count unique authors
    authors = set(c.get("author", "unknown") for c in commits)
    if authors:
        lines.append(f"by {len(authors)} author{'s' if len(authors) != 1 else ''}.")
    else:
        lines.append(".")

    if high_risk:
        lines.append(f"**{len(high_risk)} high-risk** change{'s' if len(high_risk) != 1 else ''}.")
    lines.append("")

    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue

        lines.append(f"## {label} ({len(intent_commits)})")
        lines.append("")

        for commit in intent_commits:
            lines.append(_markdown_commit_entry(commit))

        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by Agent Hub temporal digest.*")
    lines.append("")

    return "\n".join(lines)


def _markdown_commit_entry(commit: Dict) -> str:
    """Render a single commit entry in markdown."""
    subject = commit.get("subject", "Untitled")
    summary = commit.get("summary", "")
    intent = commit.get("intent", "unknown")
    risk = commit.get("risk_score", 0.0)
    modules = commit.get("modules_affected", [])
    sha = commit.get("sha", "")[:7]

    # Short subject line
    line = f"- `{intent}`: {subject}"
    if risk >= 0.5:
        line += f" ⚠️ Risk: {risk:.1f}"
    line += f" → (`{sha}`)"

    # Module list
    if modules:
        modules_str = ", ".join(modules)
        line += f"\n  Modules: `{modules_str}`"

    # Summary (if available and different from subject)
    if summary and summary != subject:
        if summary.startswith("[INSUFFICIENT_EVIDENCE]"):
            line += f"\n  _Summary unavailable_"
        else:
            line += f"\n  _{summary[:200]}_"

    return line


def _render_markdown_weekly(
    week_start: date,
    week_end: date,
    commits: List[Dict],
    grouped: Dict[str, List[Dict]],
    high_risk: List[Dict],
) -> str:
    """Render a weekly markdown digest."""
    lines = [
        f"# Weekly Changelog — {week_start.isoformat()} to {week_end.isoformat()}",
        "",
        f"**{len(commits)} commits**",
    ]
    authors = set(c.get("author", "unknown") for c in commits)
    lines.append(f"by {len(authors)} author{'s' if len(authors) != 1 else ''}.")
    if high_risk:
        lines.append(f"**{len(high_risk)} high-risk** change{'s' if len(high_risk) != 1 else ''}.")
    lines.append("")

    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        lines.append(f"## {label} ({len(intent_commits)})")
        lines.append("")
        for commit in intent_commits:
            lines.append(_markdown_commit_entry(commit))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by Agent Hub temporal digest.*")
    lines.append("")

    return "\n".join(lines)


# ── HTML rendering ────────────────────────────────────────────────

def _render_html(
    day: date,
    commits: List[Dict],
    grouped: Dict[str, List[Dict]],
    high_risk: List[Dict],
) -> str:
    """Render a daily HTML digest."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Changelog — {day.isoformat()}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; background: #f9f9f9; }}
.container {{ max-width: 900px; margin: 0 auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 0.5rem; }}
h2 {{ color: #555; margin-top: 2rem; }}
.commit {{ padding: 0.75rem; margin: 0.5rem 0; background: #f8f9fa; border-left: 3px solid #007bff; border-radius: 4px; }}
.commit.high-risk {{ border-left-color: #dc3545; background: #fff5f5; }}
.commit .intent {{ font-weight: bold; color: #007bff; text-transform: capitalize; }}
.commit .risk {{ color: #dc3545; font-weight: bold; }}
.commit .sha {{ color: #888; font-size: 0.85em; }}
.stats {{ color: #666; margin: 1rem 0; }}
.empty {{ color: #888; font-style: italic; }}
</style>
</head>
<body>
<div class="container">
<h1>Changelog — {day.isoformat()}</h1>
<div class="stats">
{'<strong>' + str(len(commits)) + ' commits</strong>' if len(commits) != 1 else '<strong>1 commit</strong>'}
"""
    authors = set(c.get("author", "unknown") for c in commits)
    html += f"\nby {len(authors)} author{'s' if len(authors) != 1 else ''}."
    if high_risk:
        html += f" <strong>{len(high_risk)} high-risk</strong> change{'s' if len(high_risk) != 1 else ''}."
    html += "\n</div>\n"

    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        html += f"\n<h2>{label} ({len(intent_commits)})</h2>\n"
        for commit in intent_commits:
            html += _html_commit_entry(commit)

    html += """
</div>
</body>
</html>"""
    return html


def _html_commit_entry(commit: Dict) -> str:
    """Render a single commit entry in HTML."""
    subject = commit.get("subject", "Untitled")
    summary = commit.get("summary", "")
    intent = commit.get("intent", "unknown")
    risk = commit.get("risk_score", 0.0)
    sha = commit.get("sha", "")[:7]
    is_high_risk = " high-risk" if risk >= 0.5 else ""

    html = f'<div class="commit{is_high_risk}">\n'
    html += f'<span class="intent">{intent}</span>: {subject}\n'
    html += f'<span class="sha">→ (`{sha}`)</span>\n'
    if risk >= 0.5:
        html += f'<span class="risk">⚠️ Risk: {risk:.1f}</span>\n'
    if summary and not summary.startswith("[INSUFFICIENT_EVIDENCE]"):
        html += f'<p>{summary[:200]}</p>\n'
    html += '</div>\n'
    return html


def _html_empty(day: date) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Changelog — {day.isoformat()}</title></head>
<body><div class="container"><h1>Changelog — {day.isoformat()}</h1>
<p class="empty">No commits.</p></div></body></html>"""


def _html_empty_module(module: str, days: int) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Changelog — {module}</title></head>
<body><div class="container"><h1>Changelog — {module}</h1>
<p class="empty">No commits in the last {days} days.</p></div></body></html>"""


# ── JSON rendering ────────────────────────────────────────────────

def _render_json(
    day: date,
    commits: List[Dict],
    grouped: Dict[str, List[Dict]],
    high_risk: List[Dict],
) -> str:
    """Render a daily JSON digest."""
    import json
    data = {
        "date": day.isoformat(),
        "total_commits": len(commits),
        "authors": list(set(c.get("author", "unknown") for c in commits)),
        "high_risk_count": len(high_risk),
        "by_intent": {INTENT_LABELS.get(k, k): v for k, v in grouped.items()},
        "commits": commits,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _json_empty(day: date) -> str:
    import json
    return json.dumps({"date": day.isoformat(), "total_commits": 0, "message": "No commits."}, indent=2)


def _json_empty_module(module: str, days: int) -> str:
    import json
    return json.dumps({"module": module, "days": days, "total_commits": 0, "message": f"No commits in the last {days} days."}, indent=2)


# ── Slack Block Kit rendering ─────────────────────────────────────

def _render_slack(
    day: date,
    commits: List[Dict],
    grouped: Dict[str, List[Dict]],
    high_risk: List[Dict],
) -> str:
    """Render a daily Slack Block Kit payload."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Changelog — {day.isoformat()}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{'*' if len(commits) != 1 else ''}{len(commits)} commits{'' if len(commits) != 1 else '*'}"
                       f" by {len(set(c.get('author', 'unknown') for c in commits))} author(s)."
                       + (f" *{len(high_risk)} high-risk* changes." if high_risk else ""),
            },
        },
    ]

    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        sections = []
        for commit in intent_commits:
            subject = commit.get("subject", "Untitled")
            sha = commit.get("sha", "")[:7]
            risk = commit.get("risk_score", 0.0)
            text = f"*{intent}*: {subject} → `{sha}`"
            if risk >= 0.5:
                text += f" ⚠️ *Risk: {risk:.1f}*"
            sections.append(text)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{label} ({len(intent_commits)})*\n" + "\n".join(sections),
            },
        })

    import json
    return json.dumps({"blocks": blocks}, ensure_ascii=False)


def _slack_empty(day: date) -> str:
    import json
    return json.dumps({
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"Changelog — {day.isoformat()}"}}
        ]
    })


def _slack_empty_module(module: str, days: int) -> str:
    import json
    return json.dumps({
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"Changelog — {module}"}}
        ]
    })


# ── Weekly/Module JSON/Slack helpers ──────────────────────────────

def _render_json_weekly(*args, **kwargs):
    """Placeholder for weekly JSON rendering."""
    import json
    return json.dumps({"message": "Weekly JSON not yet implemented"})


def _render_slack_weekly(*args, **kwargs):
    """Placeholder for weekly Slack rendering."""
    import json
    return json.dumps({"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Weekly Slack not yet implemented"}}]})


def _render_html_weekly(*args, **kwargs):
    """Placeholder for weekly HTML rendering."""
    return "<html><body><p>Weekly HTML not yet implemented</p></body></html>"


def _render_markdown_module(module: str, commits: List[Dict], grouped: Dict[str, List[Dict]], high_risk: List[Dict]) -> str:
    """Render a per-module markdown digest."""
    lines = [
        f"# Changelog — Module: {module}",
        "",
        f"**{len(commits)} commit{'s' if len(commits) != 1 else ''}** in the last 7 days.",
    ]
    if high_risk:
        lines.append(f"**{len(high_risk)} high-risk** change{'s' if len(high_risk) != 1 else ''}.")
    lines.append("")

    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        lines.append(f"## {label} ({len(intent_commits)})")
        lines.append("")
        for commit in intent_commits:
            lines.append(_markdown_commit_entry(commit))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by Agent Hub temporal digest.*")
    lines.append("")

    return "\n".join(lines)


def _render_html_module(module: str, commits: List[Dict], grouped: Dict[str, List[Dict]], high_risk: List[Dict]) -> str:
    """Render a per-module HTML digest."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Changelog — {module}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; background: #f9f9f9; }}
.container {{ max-width: 900px; margin: 0 auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 0.5rem; }}
h2 {{ color: #555; }}
.commit {{ padding: 0.75rem; margin: 0.5rem 0; background: #f8f9fa; border-left: 3px solid #007bff; }}
.commit.high-risk {{ border-left-color: #dc3545; }}
</style>
</head>
<body>
<div class="container">
<h1>Changelog — {module}</h1>
<p>{len(commits)} commit{'s' if len(commits) != 1 else ''} in the last 7 days.</p>
"""
    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        html += f"\n<h2>{label} ({len(intent_commits)})</h2>\n"
        for commit in intent_commits:
            html += _html_commit_entry(commit)

    html += """
</div>
</body>
</html>"""
    return html


def _render_json_module(module: str, commits: List[Dict], grouped: Dict[str, List[Dict]], high_risk: List[Dict]) -> str:
    """Render a per-module JSON digest."""
    import json
    data = {
        "module": module,
        "days": 7,
        "total_commits": len(commits),
        "high_risk_count": len(high_risk),
        "by_intent": {INTENT_LABELS.get(k, k): v for k, v in grouped.items()},
        "commits": commits,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _render_slack_module(module: str, commits: List[Dict], grouped: Dict[str, List[Dict]], high_risk: List[Dict]) -> str:
    """Render a per-module Slack Block Kit payload."""
    import json
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Changelog — {module}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{len(commits)} commits* in the last 7 days."},
        },
    ]
    for intent, label in INTENT_LABELS.items():
        intent_commits = grouped.get(intent, [])
        if not intent_commits:
            continue
        sections = []
        for commit in intent_commits:
            subject = commit.get("subject", "Untitled")
            sha = commit.get("sha", "")[:7]
            text = f"*{intent}*: {subject} → `{sha}`"
            sections.append(text)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{label} ({len(intent_commits)})*\n" + "\n".join(sections)},
        })
    return json.dumps({"blocks": blocks}, ensure_ascii=False)
