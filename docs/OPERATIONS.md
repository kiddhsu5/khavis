# llm-router Operations Playbook

> 給 llm-router 維護者的日常運作手冊。從每天 5 分鐘的瑣事,到每季 4 小時的策略檢視,一份完整的營運 SOP。
> Day-to-day operational playbook for the llm-router maintainer — from 5-minute daily triage to 4-hour quarterly reviews.

**Maintainer:** Kidd Hsu (solo, placeholder)
**Time budget (recommended):** 5 min/day · 30 min/week · 2 hr/month · 4 hr/quarter
**Tools:** GitHub web UI, `gh` CLI, PyPI dashboard, Docker Hub dashboard

---

## Philosophy

1. **Reasonable expectations** — solo maintainer response time is 48 hours, not "always on"
2. **Automate the boring** — Dependabot, label-bot, CI handle the rote work
3. **Write things down** — if you do it twice, write it down; if you do it three times, script it
4. **Burnout is real** — schedule downtime, block weekends, take vacations
5. **Triage before fixing** — every issue gets a label within 48h; fixes can wait

---

## Daily (5 minutes)

> Best done: morning, with coffee, before opening Slack/Twitter.

### Checklist

- [ ] **GitHub notifications** — review unread inbox (`gh notification list`)
- [ ] **Triage new issues** with labels:
  - `bug` — confirmed reproducible defect
  - `enhancement` — feature request
  - `question` — user needs help, not a code change
  - `docs` — documentation gap
  - `good first issue` — easy enough for newcomers
  - `help wanted` — community contributions welcome
  - `duplicate` — already exists (link the original)
  - `wontfix` — declined with explanation
- [ ] **Reply to discussions** — answer 1–3 open questions in GitHub Discussions
- [ ] **Mark stale issues** — if no activity in 14 days, add `stale` label
- [ ] **Pin/lock spam** — delete obvious bot comments, lock necroposts

### Triage matrix

| Symptom | Label | Action |
|---------|-------|--------|
| "X is broken" with traceback | `bug` + `needs-repro` | Reply asking for `llm-router --version` + minimal repro |
| "How do I…" question | `question` | Reply with link to docs, or write a 5-line answer inline |
| "Please add feature Y" | `enhancement` | Acknowledge, schedule for next minor, or close with explanation |
| Spelling / typo fix PR | `good first issue` (next time) | Review and merge within 24h |
| Empty issue or 1-line rage | `needs-triage` | Reply once asking for detail; close after 7 days no response |
| Security report | `security` (private) | Forward to security@kiddhsu.dev within 1 hour |

---

## Weekly (30 minutes)

> Best done: Sunday evening or Monday morning, batched.

### Checklist

- [ ] **Review open PRs** — prioritize PRs by age and size
  - [ ] < 100 lines, < 3 days old: review now
  - [ ] 100–500 lines, < 7 days old: schedule review block
  - [ ] > 500 lines or > 14 days old: ask author to split, or close with explanation
- [ ] **Check PyPI download stats** — https://pypistats.org/packages/llm-router
  - [ ] Note weekly delta (target: stable or growing)
  - [ ] If downloads dropped >30%, investigate (broken release? dep removed?)
- [ ] **Run metrics dashboard** (custom script, see Appendix A)
- [ ] **Review dependabot PRs**
  - [ ] Patch updates (`v1.0.0` → `v1.0.1`): auto-merge if CI green
  - [ ] Minor updates (`v1.0.0` → `v1.1.0`): review changelog, test locally
  - [ ] Major updates (`v1.0.0` → `v2.0.0`): defer to next minor release cycle
- [ ] **Update roadmap** — if priority changed, edit `docs/ROADMAP.md`
- [ ] **Scan HN/Reddit** for mentions (use Google Alerts or manual search)
- [ ] **Send "weekly status" tweet** — optional, builds in-public presence

### Weekly review template

Copy this into a `memory/weekly/2026-WXX.md` note:

```markdown
# Week of 2026-XX-XX

**Stats:**
- GitHub stars: 234 (+12 from last week)
- PyPI downloads (7d): 1,432 (+8%)
- Docker pulls (7d): 891 (+3%)
- New issues: 7 (3 bugs, 2 enhancements, 2 questions)
- Closed issues: 5
- Merged PRs: 4

**Highlights:**
- Released v0.1.3 (provider fix)
- First external PR from @username

**For next week:**
- [ ] Cut v0.1.4 with hotfix for issue #N
- [ ] Review pending PR #M
- [ ] Write blog post about X
```

---

## Monthly (2 hours)

> Best done: first Sunday of the month, with a calendar block.

### Checklist

- [ ] **Release planning meeting (with self)**
  - [ ] Review open `enhancement` issues
  - [ ] Decide what goes into next minor release
  - [ ] Update milestone assignments
  - [ ] Cut the next release if all features are ready
- [ ] **Dependency updates** (dependabot may have auto-handled some)
  - [ ] Verify all auto-merged PRs are clean
  - [ ] Manually bump any stale direct deps
  - [ ] Run `pip-audit` or `safety check` — file CVEs for any new findings
- [ ] **Security audit**
  - [ ] Review `.github/SECURITY.md` reports from the past month
  - [ ] Verify all dependencies are still maintained (no abandoned packages)
  - [ ] Check GitHub Dependabot security alerts — fix any High/Critical
- [ ] **Cost review** (CI minutes, storage, etc.)
  - [ ] GitHub Actions minutes used: <8,000 / 2,000 free? Buy more if needed ($0.008/min)
  - [ ] Docker Hub storage: pulls < 200 / 5 min anonymous? (fine for OSS)
  - [ ] PyPI: free, no cost concern
- [ ] **Community health check**
  - [ ] Median first-response time on issues (target: <48h)
  - [ ] Median PR review time (target: <7 days)
  - [ ] Open Discussions count (target: >0, increasing)
- [ ] **Self-care check-in**
  - [ ] Am I dreading GitHub notifications? (burnout signal)
  - [ ] Have I taken a weekend off this month? (mandatory)
  - [ ] Is the project still fun? (re-evaluate scope if not)

### Monthly review template

```markdown
# Month of 2026-XX

**Stats:**
- Total issues closed: XX
- PRs merged: XX (XX external)
- Releases shipped: vX.Y.Z, vX.Y.Z
- New contributors: X
- PyPI downloads (30d): X,XXX
- Docker pulls (30d): X,XXX

**Spend:**
- GitHub Actions: $X.XX
- Domain renewal: $X.XX/year (amortized)

**Health:**
- Median issue response: X.X hours
- Median PR review: X.X days
- Burnout score (1-10): X

**Decisions:**
- Shipped X feature, deferred Y feature
- Z contributor invited to be co-maintainer (yes / no / not yet)
```

---

## Quarterly (4 hours)

> Best done: last Sunday of the quarter, with a real calendar block.

### Checklist

- [ ] **Major version planning**
  - [ ] Which features need breaking changes?
  - [ ] Deprecation timeline for vX.0 APIs
  - [ ] RFC issues for each breaking change
  - [ ] Migration guide drafted
- [ ] **Business review** (users, revenue if SaaS)
  - [ ] Total active users (PyPI install base estimate)
  - [ ] Companies using llm-router in production (counted from issues / mentions)
  - [ ] Revenue (if Pro tier shipped)
  - [ ] Costs (CI, domain, API credits for testing)
  - [ ] Profit / loss for the quarter
- [ ] **Community health**
  - [ ] Top 10 contributors (by merged PRs)
  - [ ] Recurring vs one-time contributors ratio
  - [ ] Discussion / issue ratio (more discussions = healthier)
  - [ ] Sentiment analysis of last 50 issues (manual sample)
- [ ] **Tech debt assessment**
  - [ ] Largest module by `radon cc` (cyclomatic complexity)
  - [ ] Most-coupled module (highest import count)
  - [ ] Worst-test-covered module
  - [ ] Outdated dependencies that need migration (e.g., pydantic v2 already done?)
- [ ] **Strategy review**
  - [ ] Is the vision still valid?
  - [ ] New competitors in the space?
  - [ ] New platform opportunities (Cloudflare Workers, Vercel Edge)?
  - [ ] Time to invite a co-maintainer?

### Quarterly review template

```markdown
# Q4 2026 retrospective

## What worked
- …

## What didn't
- …

## Top 3 user requests (from issue counts)
1. …
2. …
3. …

## Top 3 confusion points (from issue comments)
1. …
2. …
3. …

## Tech debt to address next quarter
- …

## Business metrics
- Users: X
- MRR (if SaaS): $X
- Costs: $X

## Q1 2027 goals
- Ship vX.0.0 (breaking)
- Reach X,XXX stars
- Get first $X MRR

## Personal
- Burnout: low / medium / high
- Fun: high / medium / low
- Plan: keep going / scale back / hand off
```

---

## Incident Response

### Severity levels

| Sev | Definition | Fix target | Release type | Notification |
|-----|------------|-----------|--------------|--------------|
| **Sev 1** | Data loss, security breach, RCE, auth bypass | **24 hours** | Hotfix (e.g., v0.1.1) | Tweet + GH Security Advisory + email blast |
| **Sev 2** | Broken feature, broken install, major perf regression | **7 days** | Patch (e.g., v0.1.2) | Tweet + CHANGELOG + HN comment reply |
| **Sev 3** | Cosmetic, minor, edge-case bug | **Next minor** | Minor (e.g., v0.2.0) | CHANGELOG only |
| **Sev 4** | Nice-to-have, subjective, design question | Backlog | Optional | None |

### Sev 1 hotfix procedure

```bash
# 1. Branch from the affected tag
git checkout v0.1.0 -b hotfix/v0.1.1

# 2. Apply the fix
# (edit code, write a regression test)

# 3. Verify locally
pytest -x
ruff check .

# 4. Commit and tag
git add -A
git commit -S -m "fix: <one-line description>"
git tag -s v0.1.1 -m "v0.1.1 — hotfix: <description>"

# 5. Push — release.yml auto-publishes to PyPI + Docker
git push origin hotfix/v0.1.1
git push origin v0.1.1

# 6. Merge back to main
git checkout main
git merge --no-ff hotfix/v0.1.1
git push origin main

# 7. Announce (templates in Appendix B)
```

### Sev 1 communication template

**Tweet (within 1 hour):**
```
v0.1.1 hotfix shipped — addresses [Sev-1 issue #N] where [one-sentence symptom].
Upgrade now: pip install --upgrade llm-router
Affected: v0.1.0 only
Thanks to @<reporter> for the responsible disclosure.
```

**GitHub comment on the original issue:**
```
Fixed in v0.1.1 — released via the standard hotfix process. Upgrade instructions:
\`\`\`
pip install --upgrade llm-router
# or
docker pull kiddhsu/llm-router:0.1.1
\`\`\`

CVE: [if assigned]

Full advisory: https://github.com/kiddhsu/llm-router/security/advisories/[id]

Thanks for the responsible disclosure. Your name will appear in the next release notes (let me know if you'd prefer to remain anonymous).
```

### Sev 2 patch procedure

Same as Sev 1, but fix target is 7 days instead of 24 hours. Communication is less urgent — CHANGELOG entry + reply on the issue.

### Sev 3 backlog procedure

Issues tagged `severity:low` are auto-collected into the next minor milestone. Reviewed during monthly planning.

---

## Out-of-Office Policy

**The maintainer is not on-call.** Set expectations clearly in `README.md`:

> This project is maintained on a best-effort basis by a solo developer.
> Expect a first response within 48 hours on weekdays.
> No SLA on weekends or holidays (Taiwan public holidays observed).

### Vacation protocol

When taking ≥7 days off:

1. Add a pinned Discussion: "On vacation until YYYY-MM-DD, responses will be slow"
2. Set GitHub auto-responder if available
3. Add `status: maintainer-away` label to new issues (manual or via bot)
4. Defer all non-Sev-1 work

---

## Appendix A: Metrics Dashboard

We use a simple Python script (`scripts/metrics.py`, to be written) that hits the public APIs:

```python
#!/usr/bin/env python3
"""Print llm-router weekly metrics to stdout."""

import json
import urllib.request


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def main() -> None:
    # PyPI stats (last 30 days)
    pypi = get_json("https://pypistats.org/api/packages/llm-router/recent")
    print(f"PyPI downloads (last 30d): {pypi['data']['last_month']:,}")

    # GitHub stars (via public API, no auth)
    gh = get_json("https://api.github.com/repos/kiddhsu/llm-router")
    print(f"GitHub stars: {gh['stargazers_count']:,}")
    print(f"Open issues: {gh['open_issues_count']:,}")

    # Docker pulls (requires Docker Hub API token — skip if not configured)
    try:
        docker = get_json("https://hub.docker.com/v2/repositories/kiddhsu/llm-router/")
        print(f"Docker pulls: {docker['pull_count']:,}")
    except Exception:
        print("Docker pulls: (skipped — set DOCKERHUB_TOKEN)")


if __name__ == "__main__":
    main()
```

Run weekly, append output to `memory/weekly/2026-WXX.md`.

---

## Appendix B: Communication templates

### Weekly status tweet

```
llm-router weekly update:
- X new issues opened, Y closed
- v0.X.Y shipped (link)
- Z contributors this week
- <one-sentence highlight>

github.com/kiddhsu/llm-router
```

### Out-of-office auto-response

```
Thanks for opening an issue. I'm away until YYYY-MM-DD with limited connectivity.
For urgent security issues, please email security@kiddhsu.dev (still monitored).
Otherwise, expect a real response within a week of my return.

— Kidd
```

### Maintainer-handoff template (if scaling to co-maintainers)

```
Welcome @<new-maintainer> as a co-maintainer of llm-router!

Scope of your access:
- Triage rights (labels, close, no-fix)
- Merge rights for docs and tests only
- Push access to non-main branches

What I still own:
- Release tags (final approval)
- SECURITY.md reports
- @maintainers mentions

Let's sync monthly. — Kidd
```

---

## Appendix C: Tooling reference

| Tool | Purpose | Command |
|------|---------|---------|
| `gh` | GitHub CLI | `gh issue list --label bug` |
| `gh-actions` | Watch CI | `gh run watch` |
| `pypistats` | PyPI metrics | `pip install pypistats && pypistats recent llm-router` |
| `pip-audit` | CVE scan | `pip install pip-audit && pip-audit` |
| `ruff` | Lint + format | `ruff check . && ruff format .` |
| `mypy` | Type check | `mypy core/ providers/` |
| `pytest` | Tests | `pytest -x --cov=core --cov=providers` |
| `radon` | Complexity | `radon cc core/ providers/ -a` |
| `git-filter-repo` | History rewrite | Use only in private repo before launch |

---

## Appendix D: When to say no

A maintainer can't accept every contribution. Decline politely when:

| Situation | Reason | Response template |
|-----------|--------|-------------------|
| Adds a dependency > 10 MB | Bloat | "Thanks! Could you vendor this in `providers/<name>/` instead?" |
| Breaks the public API without RFC | Stability | "Please open an RFC issue first. See [link] for the process." |
| Re-implements existing functionality | Reinvention | "We already have this in `core/<module>`. Would you like to extend that?" |
| Adds a feature only the contributor needs | Scope creep | "I'd love to maintain this as a separate plugin. Want to publish it yourself?" |
| Pure style / bikeshedding PR | Time sink | "Closing as out-of-scope for now — happy to discuss in a Discussion." |
| Unverified security claim | Reputation | "Please open a private advisory. See SECURITY.md." |

Always thank the contributor before declining. Maintain the relationship.

---

**Last reviewed:** 2026-09-20 (Kidd)
**Next review:** 2026-12-20 (quarterly)
