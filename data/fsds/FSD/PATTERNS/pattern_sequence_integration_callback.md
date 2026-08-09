# Sequence Diagram Pattern — Third-party Integration Callback

## Purpose
Style for aggregator / biller / bank integrations with async callbacks.

## Example Mermaid

```mermaid
sequenceDiagram
  participant App as Channel App
  participant Core as Mobiquity Core
  participant Ext as External Partner

  App->>Core: Initiate service request
  Core->>Core: Create txn (PENDING)
  Core->>Ext: Call partner API
  Ext-->>Core: Accepted / ack
  Core-->>App: Request accepted
  Ext-->>Core: Async callback (SUCCESS/FAIL)
  Core->>Core: Update txn + notify user
```

## Notes for authors
- Always show PENDING → final state.
- Include idempotent callback handling in the FSD text near the diagram.
