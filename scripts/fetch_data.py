"""Fetch contribution calendar, repo count and featured repos from GitHub.

Runs inside the GitHub Action with GITHUB_TOKEN. Writes data/github.json,
which scripts/render_cards.py turns into the SVG cards.

If the request fails the previous data/github.json is kept, so a flaky API
call never blanks the profile.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "github.json"

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      totalCount
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

REPO_FIELDS = """
  name
  description
  url
  stargazerCount
  forkCount
  pushedAt
  primaryLanguage { name color }
"""


def graphql(token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "readme-cards",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def fetch(token: str, profile: dict) -> dict:
    login = profile["username"]
    user = graphql(token, QUERY, {"login": login})["user"]

    repos = []
    names = profile.get("featured_repos", [])
    if names:
        parts = [
            f'r{i}: repository(owner: "{login}", name: {json.dumps(n)}) {{{REPO_FIELDS}}}'
            for i, n in enumerate(names)
        ]
        data = graphql(token, "query {" + "\n".join(parts) + "}", {})
        for i, n in enumerate(names):
            repo = data.get(f"r{i}")
            if repo is None:
                print(f"warning: repo {login}/{n} not found or not public", file=sys.stderr)
                continue
            repos.append(repo)

    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for w in cal["weeks"]
        for d in w["contributionDays"]
    ]
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_contributions": cal["totalContributions"],
        "public_repos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "days": days,
        "featured": repos,
    }


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    try:
        data = fetch(token, profile)
    except Exception as exc:  # keep the last good data on any failure
        print(f"warning: could not fetch GitHub data: {exc}", file=sys.stderr)
        if OUT.exists():
            print("keeping previous data/github.json", file=sys.stderr)
            return
        raise
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{data['total_contributions']} contributions, "
        f"{data['public_repos']} public repos, {len(data['featured'])} featured"
    )


if __name__ == "__main__":
    main()
