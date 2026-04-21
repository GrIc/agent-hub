# ADR 0007: Opt-In Telemetry

## Status

Accepted

## Context

To improve Agent Hub over time, we need usage data and error reporting. However, telemetry raises privacy and security concerns, especially for proprietary codebases.





The trade-off is between product improvement (via telemetry) and user privacy (telemetry of code content).





## Decision

Implement opt-in telemetry only. Telemetry will be disabled by default and must be explicitly enabled by users via configuration.





Telemetry will include:
- **Usage metrics**: Query counts, tool usage, error rates
- **Performance metrics**: Latency, throughput, resource usage
- **Version info**: Agent Hub version, Python version, OS
- **Configuration**: Model names, RAG settings (without exposing code content)





Telemetry will **NOT** include:
- Source code content
- File paths (except to identify which files are commonly accessed)
- User queries or responses
- Personal information
- Proprietary code or business logic





## Consequences

### Positive
- Product improvement through usage data
- Error detection and debugging
- Performance optimization insights
- Respects user privacy by default
- Compliance with enterprise security requirements





### Negative
- Limited data for product decisions without opt-in
- Slower iteration without usage insights
- Need to maintain opt-in/opt-out mechanism





### Neutral
- Telemetry is disabled by default
- Users must explicitly enable it
- No impact on MCP tool contracts or functionality





## Implementation Plan

1. **Configuration**: Add `telemetry.enabled` flag to `config.yaml`
2. **Data collection**: Implement telemetry collection in web server
3. **Data transmission**: Send to telemetry service only if enabled
4. **Privacy**: Ensure no code content is transmitted
5. **Documentation**: Document telemetry opt-in process
6. **Compliance**: Add privacy policy and opt-out instructions



## Related Decisions

- DECIDE-7: Opt-in telemetry
- T-504: Execute telemetry implementation
- Phase 5: Advanced features



---


**See Also:**
- [Phase 5 — Advanced features](../roadmap/05_PHASE_ADVANCED.md)
- [Operations Guide](../operations/deploy.md)
