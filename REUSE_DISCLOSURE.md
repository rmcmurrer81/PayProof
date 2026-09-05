# Prior-work reuse disclosure

PayProof Atlas is a distinct application built for the Risk and Compliance / bookkeeping use case. The implementation, data model, fixtures, routes, tests, and interface in this repository are maintained here rather than copied wholesale from another product.

The following design lessons were intentionally carried forward from Robert McMurrer's earlier repositories:

- **ContextGate:** hash original source bytes, keep source provenance inspectable, treat imported text as untrusted evidence, fail closed when text cannot be extracted, and record corrections without erasing the original result.
- **Kira / KiraWorld:** conversation history is not automatically trusted memory. A statement becomes durable company knowledge only through an explicit, reviewable evidence or correction workflow.
- **UnitLine / UnitDay:** keep deterministic calculations and authorization boundaries outside model-generated prose, label simulated and offline behavior truthfully, and test hostile/replay/error paths separately from live-provider claims.

These are architectural principles, not a claim that PayProof inherited a live connector, model, dataset, validation result, or completed capability from those projects. No prior project's private runtime data, credentials, conversation history, identities, or user documents belong in PayProof.

Any directly reused code or asset added later must be listed here with its exact repository path, commit, license, and modifications before release or submission.
