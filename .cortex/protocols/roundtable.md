# Protocol: Roundtable

## Config
- id: roundtable
- description: Modern variant - Divergence → Critique → Synthesis
- icon: 🎭

## Phases

### 1. divergence — parallel
agents: [architect, finops, governance]
description: Each expert produces analysis in parallel.
output: rounds/divergence/{agent}.md
inputs_from: []

### 2. critique — sequential
agents: [judge]
description: Judge confronts divergent outputs.
output: rounds/critique/judge.md
inputs_from: [divergence]

### 3. synthesis — sequential
agents: [director]
description: Final arbitrated synthesis.
output: rounds/synthesis/director.md
inputs_from: [divergence, critique]

## Gates
- after: divergence
- after: critique
- after: synthesis