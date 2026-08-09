# Sequence Diagram Pattern — External Notification / SMS

## Purpose
Teach the FSD generator how we draw **web sequence diagrams** for notification flows
(SMS, email, push) using Mermaid `sequenceDiagram`.

## When to use
- OTP SMS
- Delivery callbacks from an SMS gateway
- Store-and-forward notification API

## Example Mermaid (copy this style)

```mermaid
sequenceDiagram
  participant App as Mobile App
  participant Auth as Auth Service
  participant Notify as Notification API
  participant GW as SMS Gateway

  App->>Auth: Request OTP
  Auth->>Notify: POST /notifications (template SMS_OTP)
  Notify->>Notify: Persist request
  Notify->>GW: Submit SMS
  GW-->>Notify: Accepted + providerId
  Notify-->>Auth: 202 Queued
  Auth-->>App: OTP sent
  GW-->>Notify: Delivery receipt callback
  Notify->>Notify: Update status
```

## Writing rules
- Name participants clearly (App, API, Gateway).
- Show happy path first; add failure/retry as notes or alt blocks if needed.
- Keep one diagram focused on one flow.
