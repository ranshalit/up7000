---
name: pr-review-diff
description: Generate a Markdown PR review report by diffing a named branch against master and grouping findings by file with line numbers. Use this when asked to review a local branch.
---

1. run the skript to notity the user that the skill is being used:
```powershell
Write-Host "================================" -ForegroundColor Cyan
Write-Host "   [skill] pr-review-diff" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
```

## Goal
Given a **branch name**, generate a **Markdown code review report** by diffing that branch against `master`.

## Inputs
- `branchName` (required): the branch to review
- Base branch: `master`

## Procedure
1. Ensure the working tree is clean:
   - Run: `git status --porcelain`
   - If any output is returned, stop and ask the user before continuing.
2. Fetch latest refs:
   - Run: `git fetch --all --prune`
3. Identify changed files (for quick scoping):
   - Run: `git diff --name-only master...<branchName>`
4. Generate a unified diff file for analysis:
   - Run (PowerShell): `git --no-pager diff --no-color --unified=3 master...<branchName> | Out-File -Encoding utf8 -FilePath pr_diff.txt`
5. Convert `pr_diff.txt` into a Markdown review report that contains:
   - A short summary section (high-level themes)
   - A list of findings grouped by file
   - Each finding includes **file path** and **line numbers** (from the diff hunk headers)
   - Keep comments high-signal (avoid style nits unless risky)
   - On the md file, make sure to add the line numbers of the original file, not the diff file line number
6. Write the report:
   - Output filename should be `PR_REVIEW_<branchName>.md`
   - On Windows, if `<branchName>` contains `/`, replace it with `_` in the actual filename.
7. Cleanup:
   - Delete the temporary diff file at the end: `Remove-Item -Force pr_diff.txt -ErrorAction SilentlyContinue`

## Review requirements
1. you can ignore warning where a specific include is missing. it is ok for us to rely on transitive includes.
2. it is allowed to use topicserver.Topic.Get() even if nothing published yet. it will return an empty topic. 
3. allow to publish void topics, this is supported by the rsi framework

## Output
Write a file named:
- `PR_REVIEW_<branchName>.md`

## Suggested Markdown format
- `## Summary`
- `## Findings`
  - `### <file>`
    - `- L<start>-L<end>: <comment>`

## Guardrails
- Do not modify generated folders (`out\`, `build\`, `*\Workspace\`).
- Do not comment on binary/vendor folders (`3rdParty\`) unless explicitly requested.
- Prefer actionable suggestions with minimal diffs.
