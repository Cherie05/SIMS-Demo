# Public repository setup and recruiter handoff

Repository: [Cherie05/SIMS-Demo](https://github.com/Cherie05/SIMS-Demo).
The following repository settings were applied and read back through GitHub's API on
8 October 2026. Account security and production hosting are separate steps.

## Access

| Person | Access |
|---|---|
| `Cherie05` | Owner/admin; the only current collaborator |
| Recruiters and the public | Read, clone, download and fork without an invitation |
| Outside contributors | Can propose issues and pull requests; cannot push or merge into this repository |
| Future trusted maintainer | Invite only when write access is actually needed |

Keep the repository **Public** so recruiters can open it without signing in. Do not invite
recruiters as collaborators: collaborators on a personal repository receive write access.
Public visibility allows copying and forking; repository permissions protect the original
repository, not copies. Choose a license deliberately if you want to grant reuse rights;
this setup does not add a license or change existing licensing.

Review access under [Settings → Collaborators](https://github.com/Cherie05/SIMS-Demo/settings/access).
Remove unexpected collaborators and installations. Do not share GitHub passwords or tokens.

## Main branch protection

An active [main ruleset](https://github.com/Cherie05/SIMS-Demo/rules) requires:

- A pull request for changes to `main`, including the owner's changes.
- All ten checks below, originating from GitHub Actions, with the branch up to date.
- Resolution of review conversations.
- Linear history and squash merges.
- No force pushes, deletion of `main`, or bypass actors.

Approvals are set to **0** for the current single-maintainer repository. GitHub does not let
authors approve their own pull requests. CI still has to pass before the owner merges.
When another trusted maintainer joins, require at least one approval and code-owner review.
`CODEOWNERS` points to `@Cherie05`; it routes reviews and does not grant access.

Required check names are exact, not abbreviated workflow names:

| Required check | What it verifies |
|---|---|
| `Deployment configuration and scripts` | Compose configuration, deployment/rollback, backup/restore and ShellCheck |
| `Backend (lint, types, tests, scans)` | Lint, typing, MySQL tests, coverage, dependencies and static security |
| `Frontend (lint, types, tests, build, budget)` | Lint, formatting, TypeScript, tests, build, size and dependency audit |
| `Security scans (secrets, SAST, IaC)` | Gitleaks, Semgrep, infrastructure scan and PR dependency review |
| `Container images (build, vulnerability scan, SBOM) (backend)` | Backend image build, vulnerability scan and bill of materials |
| `Container images (build, vulnerability scan, SBOM) (frontend)` | Frontend image build, vulnerability scan and bill of materials |
| `End-to-end acceptance (PDF brief) + DAST` | Browser acceptance, monitoring checks and OWASP ZAP |
| `analyze (python)` | Python CodeQL analysis |
| `analyze (javascript-typescript)` | Frontend CodeQL analysis |
| `analyze (actions)` | Workflow CodeQL analysis |

Update the ruleset if these job names change. Do not merge a change merely because a workflow
started: inspect the checks on that pull request's latest commit. Old failures remain visible
in Actions history; judge the current commit. Completed feature branches are automatically
deleted after merge. Automatic merging of dependency updates is disabled.

## Security and workflow permissions

| Setting | Applied value |
|---|---|
| Dependency graph | Enabled; dependency SBOM API returns the resolved graph |
| Dependabot alerts | Enabled |
| Dependabot security updates | Enabled; fixes arrive as pull requests |
| Dependabot version updates | Weekly config in `.github/dependabot.yml`, with a seven-day cooldown |
| Secret scanning | Enabled |
| Secret push protection | Enabled |
| Private vulnerability reporting | Enabled; linked in `SECURITY.md` |
| Default `GITHUB_TOKEN` permission | Read |
| Actions allowed to create/approve PRs | Disabled |
| Fork workflow approval | Required for all external contributors |

Review these in [Advanced Security](https://github.com/Cherie05/SIMS-Demo/settings/security_analysis)
and [Actions settings](https://github.com/Cherie05/SIMS-Demo/settings/actions).
Individual trusted jobs request limited extra permissions for security reports and release
artifacts. Actions are pinned to full commit SHAs. Keep fork pull requests on `pull_request`;
do not switch to privileged `pull_request_target` and execute an untrusted branch with secrets.
Review workflow changes before approving an outside contributor's run.

The initial CI failure was ShellCheck 0.9.0 treating callbacks invoked through `check "$@"`
as unreachable. Only those callbacks have scoped `SC2317,SC2329` annotations; lint remains
enabled for all scripts. Backup validation uses explicit `if` guards for `SC2015`.
PR dependency review separately required enabling the dependency graph. The gates were retained.

Keep real `.env` files, credentials, databases, logs, private keys and personal recording notes
out of Git and source ZIPs. `.env.example` and documented synthetic demo accounts are suitable
for the reviewer. If a real credential is exposed, revoke/rotate it before cleaning history;
deleting a file from the latest commit does not remove older copies.

## Owner account and production releases

The owner should enable **two-factor authentication**, preferably a passkey or authenticator,
and save recovery codes privately in [account security](https://github.com/settings/security).
This repository setup does not configure the owner's authentication factors.

Recruiter submission needs no production deployment secrets. The release workflow runs on
`v*.*.*` tags and requires a real registry and host setup. Before using it, configure `staging`
and `production` environments, restrict deployment refs, set production approval with another
trusted reviewer, and add only the documented environment secrets. Keep production credentials
away from PR jobs. Do not push a release tag simply to label the assignment ZIP while the
deployment workflow is unconfigured.

## What a recruiter should receive

1. The public repository URL above, pointing to a passing `main` commit.
2. A source ZIP generated from that same commit. GitHub's **Code → Download ZIP** downloads
   tracked source; a local `git archive` can also create it. Exclude dependencies, `.env`,
   local databases, test caches and the ignored `LOOM_VIDEO_SCRIPT.md`.
3. A Loom link that opens for people who have the link. Check it from a signed-out browser.

The README includes screenshots, architecture, requirement mapping, synthetic demo accounts,
Docker quick start, native setup and test commands. [RUN_COMMANDS.md](../RUN_COMMANDS.md)
contains the Windows commands. Start with the demo stack; the native path also needs MySQL.
The repository About description and topics identify the stack and assignment features.
The README badges link to the live CI and CodeQL results.

A deployed website URL is optional under the supplied submission guidelines. If included,
use actual HTTPS, SMTP and production secrets. `localhost` URLs only work on the reviewer's
own computer after starting the app. Do not claim hosting is available from this repository
setup alone. Send the repository, source ZIP and Loom link to HR yourself.

## Future changes

From an up-to-date `main`, use a branch and pull request:

```powershell
git switch main
git pull --ff-only origin main
git switch -c fix/describe-the-change
# Edit and run the checks appropriate to your change.
git add <specific-files>
git commit -m "fix: describe the change"
git push -u origin fix/describe-the-change
```

Open the pull request on GitHub, wait for all required checks, resolve review conversations,
then squash merge. Return to `main` and pull before starting the next branch. Investigate failed
Dependabot PRs individually, especially major-version updates; do not bypass a failed gate.

References: GitHub's [personal-repository permissions](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository),
[rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets),
[fork approvals](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks),
and [Dependabot alerts/dependency graph](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependabot-alerts).
