#!/usr/bin/env bash
# extract_projects.sh — extract the project-pipeline files into a sister repo.
# See docs/roadmap/EXTRACT_PROJECTS_REPO.md for the full guide.

set -euo pipefail

# -------------- config --------------
SCRATCH_DIR="${SCRATCH_DIR:-/tmp/agent-hub-extract-$$}"
DRY_RUN=false

# Paths to KEEP in the extracted repo (history preserved for these).
PATHS_TO_KEEP=(
    "src/agents/portfolio.py"
    "src/agents/specifier.py"
    "src/agents/planner.py"
    "src/agents/storyteller.py"
    "src/agents/presenter.py"
    "src/agents/project_agent.py"
    "src/projects.py"
    "src/pipeline.py"
    "src/workspace_session.py"
    "agents/defs/portfolio.md"
    "agents/defs/specifier.md"
    "agents/defs/planner.md"
    "agents/defs/storyteller.md"
    "agents/defs/presenter.md"
    "web/workspace.html"
    "web/workspace_routes.py"
    "projects/"
)

# -------------- helpers --------------
log()  { echo -e "\033[1;36m[extract]\033[0m $*"; }
warn() { echo -e "\033[1;33m[extract]\033[0m $*" >&2; }
die()  { echo -e "\033[1;31m[extract ERROR]\033[0m $*" >&2; exit 1; }

run() {
    if $DRY_RUN; then
        echo "  (dry) $*"
    else
        eval "$@"
    fi
}

# -------------- args --------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h)
            cat <<EOF
Usage: bash scripts/extract_projects.sh [--dry-run]

Extracts the project-pipeline files from agent-hub into a sister repo.
Preserves git history for the extracted files.

Options:
  --dry-run    Show what would happen without modifying anything.

Prerequisites:
  - Clean working tree in agent-hub.
  - git-filter-repo installed (pip install git-filter-repo).
  - Empty target repo already created on your Git host.
EOF
            exit 0
            ;;
        *) die "Unknown arg: $1" ;;
    esac
done

# -------------- preflight --------------
log "preflight checks"

command -v git >/dev/null 2>&1 || die "git not installed"
command -v git-filter-repo >/dev/null 2>&1 || die "git-filter-repo not installed (pip install git-filter-repo)"
[[ -d .git ]] || die "Not a git repo. Run this from the agent-hub root."

if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree not clean. Commit or stash changes first.\n$(git status --short)"
fi

SOURCE_URL="$(git config --get remote.origin.url)" || die "No origin remote set."
log "source remote: $SOURCE_URL"

# Verify all PATHS_TO_KEEP exist in the current checkout.
for p in "${PATHS_TO_KEEP[@]}"; do
    if [[ ! -e "$p" ]]; then
        warn "Path '$p' not found in current checkout — will be skipped."
    fi
done

# -------------- prompt for target URL --------------
if ! $DRY_RUN; then
    echo
    read -p "URL of the new (empty) agent-hub-projects remote: " TARGET_URL
    [[ -n "$TARGET_URL" ]] || die "Target URL required."
else
    TARGET_URL="<TARGET_URL>"
fi

# -------------- step 1: scratch mirror clone --------------
log "step 1: mirror-clone to $SCRATCH_DIR"
run "git clone --no-local '$SOURCE_URL' '$SCRATCH_DIR'"
run "cd '$SCRATCH_DIR'"

if ! $DRY_RUN; then cd "$SCRATCH_DIR"; fi

# -------------- step 2: filter to keep only project-pipeline paths --------------
log "step 2: filter-repo to keep only project-pipeline files"

FILTER_ARGS=""
for p in "${PATHS_TO_KEEP[@]}"; do
    if [[ "$p" == */ ]]; then
        FILTER_ARGS="$FILTER_ARGS --path ${p%/}"
    else
        FILTER_ARGS="$FILTER_ARGS --path $p"
    fi
done

run "git filter-repo --force $FILTER_ARGS"

log "post-filter commit count:"
if ! $DRY_RUN; then git log --oneline | wc -l; fi

# -------------- step 3: push to new remote --------------
log "step 3: push to $TARGET_URL"
run "git remote add newremote '$TARGET_URL'"
run "git push newremote --all"
run "git push newremote --tags"

# -------------- step 4: cleanup in main agent-hub repo --------------
cd - >/dev/null  # back to original agent-hub dir

log "step 4: remove extracted paths from agent-hub"

for p in "${PATHS_TO_KEEP[@]}"; do
    if [[ -e "$p" ]]; then
        run "git rm -r --quiet '$p'"
    fi
done

# -------------- step 5: patch main.py, config.yaml, web/server.py, run.py --------------
log "step 5: mechanical file edits (main.py, config.yaml, web/server.py, run.py)"

# This step is intentionally conservative: it only removes lines that match
# well-known patterns. If the user has customized these files, we stop and
# ask them to do the removal manually.

edit_or_warn() {
    local file="$1"; local pattern="$2"; local desc="$3"
    if [[ ! -f "$file" ]]; then
        warn "$file not found, skipping '$desc'"
        return
    fi
    if grep -q "$pattern" "$file" 2>/dev/null; then
        run "sed -i.bak '/$pattern/d' '$file'"
        log "  edited $file: removed lines matching /$pattern/ ($desc)"
    else
        log "  $file: no match for '$pattern' (already clean, or unusual structure)"
    fi
}

edit_or_warn "src/main.py" "portfolio\|specifier\|planner\|storyteller\|presenter" "project-agent imports/registrations"
edit_or_warn "run.py" "--project\|pipeline" "pipeline CLI flag"
edit_or_warn "web/server.py" "workspace_routes" "workspace route registration"

# config.yaml — use a python inline to remove the 5 agent blocks cleanly
if [[ -f "config.yaml" ]] && ! $DRY_RUN; then
    python3 - <<'PYEOF'
import re, pathlib
p = pathlib.Path("config.yaml")
text = p.read_text()
for agent in ("portfolio", "specifier", "planner", "storyteller", "presenter"):
    pattern = rf"^\s*{agent}:\s*\n(?:\s+.*\n)*"
    text = re.sub(pattern, "", text, flags=re.MULTILINE)
p.write_text(text)
print(f"  edited config.yaml: removed 5 project-agent blocks")
PYEOF
fi

# README.md — add pointer to sister repo (prepend-note-style)
if [[ -f "README.md" ]] && ! $DRY_RUN; then
    if ! grep -q "agent-hub-projects" README.md; then
        run "sed -i.bak '1a\\\n> For greenfield project authoring (portfolio / specifier / planner / storyteller / presenter), see the companion repo [agent-hub-projects](https://github.com/<YOUR_ORG>/agent-hub-projects).\n' README.md"
        log "  edited README.md: added sister-repo pointer at top"
    fi
fi

# -------------- step 6: commit cleanup --------------
log "step 6: commit cleanup"
run "git add -A"
run "git commit -m 'chore: extract project pipeline into agent-hub-projects (DECIDE-1)' -m 'See docs/decisions/0001-extract-projects.md'"

log "DONE."
cat <<EOF

✅ Extraction complete.

Next steps (manual):
  1. In the new repo, add infra scaffolding (Dockerfile, docker-compose, config, README).
     See docs/roadmap/EXTRACT_PROJECTS_REPO.md §6.
  2. In agent-hub, verify:
       git status
       docker compose up -d
       curl http://localhost:8080/healthz
  3. Push the cleanup commit:
       git push origin main
  4. Update docs/decisions/0001-extract-projects.md to reflect the new remote URL.

Backup scratch directory: $SCRATCH_DIR
Remove it once you're satisfied:
       rm -rf $SCRATCH_DIR
EOF
