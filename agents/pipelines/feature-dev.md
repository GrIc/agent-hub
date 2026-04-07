# Pipeline: Feature Development

## Config
- id: feature-dev
- description: End-to-end feature development from notes to implementation
- openwebui: yes
- icon: 🔄
- scope: project

## Steps

### 1. portfolio — Requirements
Transform notes into functional requirements.
output: requirements

### 2. specifier — Specifications + Architecture
Translate requirements into technical specifications and architecture.
output: specifications

### 3. planner — Roadmap
Break specifications into tasks with timeline.
output: roadmap

### 4. storyteller — Synthesis
Produce a unified techno-functional synthesis document.
output: synthesis

### 5. presenter — Presentation
Create a 10-slide deck from the synthesis.
output: deck

### 6. developer — Implementation
Generate git diffs for each planned task.

## Commands
- /finalize — validate current step and proceed
- /draft — regenerate current step output
- /back — return to previous step
- /status — show pipeline progress
- /abort — cancel pipeline
