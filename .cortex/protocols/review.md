# Protocol: Review

## Config
- id: review
- description: Multi-expert review of final deliverable
- icon: 📝

## Phases

### 1. review — parallel
agents: [architect, finops, governance, jury, tech_expert]
description: Each expert reviews the deliverable from their perspective.
output: rounds/review/{reviewer}.md
inputs_from: []

### 2. digest — sequential
agents: [director]
description: Consolidate all reviews into a synthesis.
output: rounds/digest/director.md
inputs_from: [review]

## Gates
- after: review
- after: digest