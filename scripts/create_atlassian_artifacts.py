#!/usr/bin/env python3
"""Create Jira issues and a Confluence page for the 2026 development plan.

The script defaults to dry-run mode so the GitHub Actions workflow can preview
planned Atlassian changes before creating anything. It reads credentials only
from process environment variables and never prints the API token.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


COMMON_LABEL = "personal-development"


@dataclass(frozen=True)
class JiraIssue:
    issue_type: str
    summary: str
    labels: tuple[str, ...]
    description: str


JIRA_ISSUES: tuple[JiraIssue, ...] = (
    JiraIssue(
        issue_type="Epic",
        summary="Driving License — Summer 2026",
        labels=(COMMON_LABEL, "driving-license"),
        description=(
            "Short-term summer project to finish driving school by the end of "
            "June, take additional lessons, and pass the driving exam in July "
            "or August. Expected output: exam-ready checklist, scheduled "
            "practice lessons, and weekly progress updates."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="Master’s Degree — Autumn 2026",
        labels=(COMMON_LABEL, "masters"),
        description=(
            "Autumn education project to complete application and startup "
            "tasks for the selected master’s program. Expected output: "
            "submitted documents, confirmed requirements, and a sustainable "
            "study rhythm that supports long-term backend/.NET career growth."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="Lead Software Engineer Assessment",
        labels=(COMMON_LABEL, "lead-assessment", "system-design", "dotnet", "architecture", "highload"),
        description=(
            "Main career development track for Lead Software Engineer "
            "assessment readiness. Expected output: phased roadmap, daily "
            "practice tasks, Confluence notes, STAR stories, and mock "
            "interview feedback."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="Apartment — Autumn 2026",
        labels=(COMMON_LABEL, "apartment"),
        description=(
            "Autumn life project for apartment paperwork and setup. Expected "
            "output: administrative checklist, legal/financial tasks, setup "
            "tasks, and risk tracking."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="English — Evergreen",
        labels=(COMMON_LABEL, "english"),
        description=(
            "Evergreen English habit on Monday and Wednesday from 13:00 to "
            "14:30. Expected output: consistent lessons and practice connected "
            "to technical communication, system design explanations, and "
            "interview answers."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="Gym — Evergreen",
        labels=(COMMON_LABEL, "gym"),
        description=(
            "Evergreen gym habit on Tuesday, Thursday, and Saturday mornings. "
            "Expected output: consistent 1–1.5 hour sessions focused on "
            "energy, discipline, and sustainability."
        ),
    ),
    JiraIssue(
        issue_type="Epic",
        summary="Weekly Reviews",
        labels=(COMMON_LABEL, "weekly-review"),
        description=(
            "Weekly operating-system review every Sunday. Expected output: "
            "planned vs completed comparison, blockers, wins, top 3 priorities, "
            "habit tracking, Lead assessment hours, and realistic adjustments."
        ),
    ),
)

CONFLUENCE_PAGE_TITLE = "Personal Development Plan 2026"

CONFLUENCE_PAGE_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Development goals",
        (
            "Get driving license this summer.",
            "Start master’s degree this autumn.",
            "Prepare for a Lead Software Engineer assessment in autumn or December.",
            "Complete apartment paperwork and setup this autumn.",
            "Maintain English as an evergreen skill.",
            "Go to the gym consistently as an evergreen habit.",
        ),
    ),
    (
        "Weekly operating system",
        (
            "Monday: English 13:00–14:30 and assessment prep on System Design.",
            "Tuesday: Gym in the morning and assessment prep on .NET / Backend depth.",
            "Wednesday: English 13:00–14:30 and assessment prep on architecture patterns.",
            "Thursday: Gym in the morning and assessment prep on distributed systems / HighLoad.",
            "Friday: Assessment prep on leadership / behavioral stories.",
            "Saturday: Gym in the morning plus mock interview, large case study, or deep work.",
            "Sunday: Weekly review, light assessment review, and planning for next week.",
        ),
    ),
    (
        "Lead Software Engineer roadmap",
        (
            "Phase 1 — Foundation: system design basics, scalability, databases, queues, .NET fundamentals, Clean Architecture, modular monolith, and microservices basics.",
            "Phase 2 — Depth: distributed systems, consistency, event-driven architecture, observability, reliability, SQL optimization, ASP.NET Core internals, and concurrency.",
            "Phase 3 — Leadership: mentoring, technical ownership, conflict resolution, decision-making, stakeholder communication, incident leadership, culture, delivery, and prioritization.",
            "Phase 4 — Assessment readiness: mock interviews, STAR stories, trade-off explanations, English technical speaking, and final weak-area review.",
        ),
    ),
    (
        "Weekly review template",
        (
            "What was planned, completed, and not completed?",
            "Why was work not completed, and what should change next week?",
            "What were the main win and blocker?",
            "What are the top 3 priorities for next week?",
            "Were gym and English sessions completed?",
            "How many Lead assessment preparation hours were completed?",
            "What should be moved, deleted, simplified, or delegated?",
        ),
    ),
)


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").strip().lower() not in {"false", "0", "no", "off"}


def require_env(name: str, *, secret: bool = False) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        kind = "secret" if secret else "environment variable"
        raise RuntimeError(f"Missing required {kind}: {name}")
    return value


def adf_text(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def confluence_storage_body() -> str:
    sections = []
    for heading, items in CONFLUENCE_PAGE_SECTIONS:
        list_items = "".join(f"<li>{escape(item)}</li>" for item in items)
        sections.append(f"<h2>{escape(heading)}</h2><ul>{list_items}</ul>")

    jira_items = "".join(
        f"<li><strong>{escape(issue.summary)}</strong> — {escape(', '.join(issue.labels))}</li>"
        for issue in JIRA_ISSUES
    )
    return "".join(
        (
            "<p>This page is generated from the personal-development-manager-agent repository.</p>",
            "".join(sections),
            "<h2>Jira epics to create</h2>",
            f"<ul>{jira_items}</ul>",
        )
    )


class AtlassianClient:
    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        credentials = f"{email}:{token}".encode("utf-8")
        self.auth_header = "Basic " + base64.b64encode(credentials).decode("ascii")

    def request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self.auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as error:
            safe_body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Atlassian API request failed: {method} {path} -> {error.code}: {safe_body}") from error
        except URLError as error:
            raise RuntimeError(f"Atlassian API request failed: {method} {path} -> {error.reason}") from error

    def create_jira_issue(self, project_key: str, issue: JiraIssue) -> dict[str, Any]:
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": issue.summary,
                "issuetype": {"name": issue.issue_type},
                "labels": list(issue.labels),
                "description": adf_text(issue.description),
            }
        }
        return self.request("POST", "/rest/api/3/issue", payload)

    def create_confluence_page(self, space_id: str, parent_id: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "spaceId": space_id,
            "status": "current",
            "title": CONFLUENCE_PAGE_TITLE,
            "body": {
                "representation": "storage",
                "value": confluence_storage_body(),
            },
        }
        if parent_id:
            payload["parentId"] = parent_id
        return self.request("POST", "/wiki/api/v2/pages", payload)


def preview(project_key: str, space_id: str, parent_id: str | None) -> None:
    print("Dry-run mode is enabled. No Jira issues or Confluence pages will be created.")
    print(f"Jira project: {project_key}")
    for issue in JIRA_ISSUES:
        print(f"- Jira {issue.issue_type}: {issue.summary} [{', '.join(issue.labels)}]")
    parent_label = parent_id if parent_id else "none"
    print(f"Confluence space ID: {space_id}; parent page ID: {parent_label}")
    print(f"- Confluence page: {CONFLUENCE_PAGE_TITLE}")


def main() -> int:
    dry_run = is_dry_run()
    token = require_env("ATLASSIAN_API_TOKEN", secret=True)
    email = require_env("ATLASSIAN_EMAIL")
    base_url = require_env("ATLASSIAN_BASE_URL")
    project_key = require_env("JIRA_PROJECT_KEY")
    space_id = require_env("CONFLUENCE_SPACE_ID")
    parent_id = os.environ.get("CONFLUENCE_PARENT_ID", "").strip() or None

    if dry_run:
        preview(project_key, space_id, parent_id)
        return 0

    client = AtlassianClient(base_url=base_url, email=email, token=token)
    print("Dry-run mode is disabled. Creating Atlassian artifacts.")
    for issue in JIRA_ISSUES:
        created_issue = client.create_jira_issue(project_key, issue)
        print(f"Created Jira issue {created_issue.get('key', '<unknown>')}: {issue.summary}")

    created_page = client.create_confluence_page(space_id, parent_id)
    print(f"Created Confluence page {created_page.get('id', '<unknown>')}: {CONFLUENCE_PAGE_TITLE}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
