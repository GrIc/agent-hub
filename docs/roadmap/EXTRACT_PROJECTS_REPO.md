# EXTRACT_PROJECTS_REPO — DECIDE-1 execution guide

> Goal: extract the greenfield-project pipeline (portfolio / specifier / planner / storyteller / presenter) from `agent-hub` into a sister repo `agent-hub-projects`, preserving the git history of the extracted files.

---

## 1. Why we're extracting, not deleting

The project pipeline is a valid product — it just targets a different audience (greenfield project authors) than Agent Hub's MCP thesis (coding agents on existing codebases). Extracting preserves the work and lets each repo tell a coherent story.

History preservation matters because:
- The project pipeline has commit history worth keeping.
- Rewriting commits in both repos would destroy `git blame` usefulness.
- Future contributors may want to fork either side.

---

## 2. Prerequisites

1. **git-filter-repo installed**. On the container / your dev machine:
   ```bash
   pip install git-filter-repo
   # or: brew install git-filter-repo
   # or: apt install git-filter-repo
   ```
2. **A new empty GitLab/GitHub repo** created: `agent-hub-projects` (empty, no README, no license, no initial commit).
3. **Write access to both repos** via SSH key or HTTPS token.
4. **A clean working tree** on the main `agent-hub` checkout. Commit or stash anything in flight.
5. **A backup**. Before anything destructive: `git clone --mirror <agent-hub-url> agent-hub.mirror.bak`.

---

## 3. The script

Use `scripts/extract_projects.sh` (next document). High-level flow:

```
Step 1:  Mirror-clone agent-hub to a scratch directory.
Step 2:  In the scratch clone, run git-filter-repo to KEEP ONLY the
         project-pipeline files (paths listed below). History is rewritten
         to contain only commits that touched those files.
Step 3:  Add the new `agent-hub-projects` remote and push.
Step 4:  In the main agent-hub repo, delete the now-extracted files and
         commit the cleanup.
Step 5:  Verify both repos build / start.
```

---

## 4. Paths kept in `agent-hub-projects`

```
src/agents/portfolio.py
src/agents/specifier.py
src/agents/planner.py
src/agents/storyteller.py
src/agents/presenter.py
src/agents/project_agent.py
src/projects.py
src/pipeline.py
src/workspace_session.py
agents/defs/portfolio.md
agents/defs/specifier.md
agents/defs/planner.md
agents/defs/storyteller.md
agents/defs/presenter.md
web/workspace.html
web/workspace_routes.py
projects/
```

**Not kept**: infrastructure (Dockerfile, docker-compose.yml, config.yaml, LICENSE, README.md, requirements.txt). The new repo authors its own infra scaffolding post-extraction (a lightweight copy of Agent Hub's, minus MCP, minus codex, minus graph, minus temporal).

---

## 5. Running the script

```bash
cd /path/to/agent-hub

# Preview: show what would happen without making changes to any remote.
bash scripts/extract_projects.sh --dry-run

# Real run. Prompts for the new remote URL.
bash scripts/extract_projects.sh
```

---

## 6. What the script does NOT do (you must do manually)

After the script completes successfully, in the new `agent-hub-projects` repo:

1. **Add infra scaffolding**:
   - Copy `Dockerfile`, `docker-compose.yml`, `config.yaml.example`, `.env.example`, `requirements.txt` from Agent Hub.
   - Strip config sections irrelevant to projects (MCP, codex, graph, temporal).
   - Keep only `expert`, `documenter`, and the 5 project agents in config.
2. **Rewrite README.md** to pitch the project-authoring use case.
3. **Add LICENSE** (Apache 2.0, matching parent repo's choice).
4. **Set up CI** (`.gitlab-ci.yml`) for the new repo independently.

These are manual because they are creative decisions, not mechanical transformations.

---

## 7. Cleanup in `agent-hub` (after extraction)

The script handles this too, but verify:

```bash
cd /path/to/agent-hub
git status                                # should be clean

# Verify no stale imports remain
grep -rn "from src.agents.portfolio\|from src.agents.specifier\|from src.projects\|from src.pipeline" src/ web/ run.py || echo "OK: no stale imports"

# Run tests
pytest tests/ || echo "check failures"

# Start up
docker compose up -d
curl http://localhost:8080/healthz
```

Files the script removes in `agent-hub`:
- All paths listed in §4.

Files the script **modifies** in `agent-hub`:
- `src/main.py` — removes imports and menu entries for the 5 project agents.
- `config.yaml` — removes `agents.portfolio`, `.specifier`, `.planner`, `.storyteller`, `.presenter`.
- `web/server.py` — removes `/workspace` route registration.
- `README.md` — removes "Project Pipeline" section and adds pointer to the sister repo.
- `run.py` — removes `--project` argument and pipeline branches.

Any file modification that can't be done mechanically (e.g. you had custom changes to `main.py`) will stop the script with a clear error and leave you in a partial state to resolve manually. See §8.

---

## 8. Rollback

If anything goes wrong:

1. **Before pushing to new repo**: `rm -rf agent-hub-extract-scratch/` (the scratch directory). Nothing was changed in the new repo's remote yet.
2. **After pushing to new repo but before agent-hub cleanup commit**: delete the new repo on GitHub/GitLab (fresh one, nothing lost). Repeat.
3. **After agent-hub cleanup commit**:
   - `git log --oneline -5` — find the SHA before cleanup.
   - `git reset --hard <sha-before-cleanup>`
   - If already pushed: `git push --force origin main` (careful; only OK if no one else pulled).
4. **Worst case**: restore from mirror backup you made in §2:
   ```bash
   cd /tmp
   git clone agent-hub.mirror.bak agent-hub-restored
   cd agent-hub-restored
   git push --force <agent-hub-url> main
   ```

---

## 9. Success criteria

After running the script and completing §6:

- [ ] `agent-hub-projects` repo: `git log --oneline | head -20` shows real historical commits (not a single extraction commit).
- [ ] `agent-hub-projects` repo: `find . -name "portfolio.py"` returns a hit.
- [ ] `agent-hub-projects` repo: `docker compose up -d` starts (after you added infra in §6).
- [ ] `agent-hub` repo: `find agents/defs -name "*.md"` shows only `codex.md`, `documenter.md`, `expert.md` (plus user customs).
- [ ] `agent-hub` repo: `docker compose up -d` starts.
- [ ] `agent-hub` repo: `pytest` passes.
- [ ] `agent-hub/README.md` has a link to the `agent-hub-projects` repo in one line.

---

## 10. FAQ

**Q: Can I skip history preservation and just copy files?**
A: Yes, but you'll lose `git blame`. Not recommended unless the history is very noisy. In that case: remove the `git-filter-repo` step from the script and replace with `cp -r` then `git commit`.

**Q: What if I've customized files in the extracted set?**
A: The script warns on modified files (`git status --porcelain` before extraction). You should commit or stash those changes first. The extraction preserves all commits, including yours.

**Q: Can I re-run the script to update the extracted repo later?**
A: No, not directly. `git-filter-repo` rewrites history; you can't incrementally push rewrites. If the repos diverge, manually port commits with `git cherry-pick` or a fresh extraction into a new branch.

**Q: What about secrets in history?**
A: `git-filter-repo` does not scan for secrets. Before pushing the new repo, run `git secrets --scan-history` or `trufflehog` on the scratch directory. If anything is found, extend the script's filter to also `--invert-paths` scrub the offending files.

---

*Proceed to `scripts/extract_projects.sh`.*
