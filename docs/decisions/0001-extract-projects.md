# 0001-extract-projects.md

## Context
The greenfield project pipeline (portfolio → specifier → planner → storyteller → presenter) is a coherent product but targets a different user (PM/architect doing greenfield design) than Agent Hub's MCP thesis (coding agents on existing codebases). Extracting it to a sister repo preserves the work and lets each repo tell a coherent story.

## Options considered
1. **Delete the pipeline code**: Lose history and contributions.
2. **Extract with git-filter-repo**: Preserve history in a new repo.
3. **Keep in place**: Continue to dilute the MCP message.

## Decision
We chose option 2: extract the project pipeline to a sister repo `agent-hub-projects` using `git-filter-repo` to preserve git history.

## Consequences
- New repo `agent-hub-projects` created at https://github.com/GrIc/agent-hub-projects with intact git history for the extracted files.
- In `agent-hub`:
  - Removed: src/agents/portfolio.py, src/agents/specifier.py, src/agents/planner.py, src/agents/storyteller.py, src/agents/presenter.py, src/agents/project_agent.py, src/projects.py, src/pipeline.py, src/workspace_session.py, agents/defs/portfolio.md, agents/defs/specifier.md, agents/defs/planner.md, agents/defs/storyteller.md, agents/defs/presenter.md, web/workspace.html, web/workspace_routes.py, projects/ directory.
  - Updated: src/main.py (removed imports and menu entries for the 5 project agents), config.yaml (removed agent sections), web/server.py (removed /workspace route registration), run.py (removed --project argument and pipeline branches), README.md (added pointer to sister repo).
- The agent-hub repo now focuses solely on the MCP server for code intelligence.
- The new repo requires manual addition of infra scaffolding (Dockerfile, docker-compose, config, README) and setup of CI.
