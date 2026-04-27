# Protocol: Foundry

## Config
- id: foundry
- description: Legacy 5-phase pipeline (linear ingestion → synthesis)
- icon: 🔧

## Phases

### 1. intake — sequential
agents: [coach]
description: Initial brief intake and context gathering.
output: rounds/intake/coach.md
inputs_from: []

### 2. analysis — parallel
agents: [architect, finops, governance]
description: Multi-expert analysis of the brief.
output: rounds/analysis/{agent}.md
inputs_from: [intake]

### 3. positioning — sequential
agents: [positioning]
description: Build positioning strategy.
output: rounds/positioning/positioning.md
inputs_from: [analysis]

### 4. design — sequential
agents: [designer]
description: Design presentation materials.
output: rounds/design/designer.md
inputs_from: [positioning]

### 5. synthesis — sequential
agents: [director]
description: Final synthesis and recommendations.
output: rounds/synthesis/director.md
inputs_from: [analysis, positioning, design]

## Gates
- after: intake
- after: analysis
- after: positioning
- after: design
- after: synthesis