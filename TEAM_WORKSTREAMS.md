# PayProof Atlas — Three-Team Work Split

These workstreams are intentionally separated by file ownership so three people can work in parallel without overwriting one another. Create one branch per workstream and merge through pull requests.

## 1. Visual / 3D assurance experience

**Owner:** Mike

**Branch:** `feature/3d-assurance-ui`

**Owns:** `static/index.html`, `static/app.js`, `static/styles.css`, and visual assets under `static/`.

**Deliverables**

- Replace the flat node map with a polished, genuinely depth-aware 3D assurance graph.
- Make the four status cards clickable and filter/drill into matching controls.
- Replace the misleading geographic "stakeholders" view with systems, people, evidence owners, and dependencies.
- Convert Evidence from a large table into a compact summary with click-to-expand details.
- Preserve the no-page-scroll control-room layout at common laptop and desktop sizes.
- Keep keyboard controls, reduced-motion behavior, visible focus states, and text alternatives.

**Acceptance checks**

- Every node, card, legend item, and evidence summary has a useful action.
- Selecting an object shows its status, confidence, conflicts, and cited evidence.
- The UI remains usable at 1366x768, 1440x900, and 1920x1080 without vertical page scrolling.

## 2. Bank feed / reconciliation engine

**Owner:** Codex / backend teammate

**Branch:** `feature/bank-reconciliation`

**Owns:** backend bank/reconciliation modules, related routes in `app.py`, bank fixtures, and focused automated tests. Coordinate before editing shared core sections.

**Deliverables**

- Add safe statement import with preview-before-commit for CSV/OFX/QFX where supported.
- Provide truthful live-bank connection status; never collect or store online-banking passwords.
- Expose settings actions to add a bank source, connect/reconnect email, preview local removal impact, and explicitly remove a local connection.
- State that disconnecting PayProof does not delete anything from the upstream bank or email provider.
- Match bank transactions against intake receipts, expense reports, and email-derived records.
- Explain match confidence and mismatches; do not invent missing records.
- Detect vendor/category spikes such as unusual Amazon food-and-drink spending and suggest possible cuts as recommendations, not facts.

**Acceptance checks**

- Import preview reports accepted/rejected rows before database changes.
- Re-importing the same statement does not duplicate transactions.
- Exact, probable, conflicting, and unmatched outcomes are covered by tests.
- Each recommendation exposes the underlying transactions and calculation.

## 3. Intake / evidence / judge-ready demo

**Owner:** Codex / workflow and QA teammate

**Branch:** `feature/intake-demo-qa`

**Owns:** demo fixtures, security evidence samples, demo documentation, QA checklists, and dedicated workflow tests. Coordinate before changing shared backend or UI files.

**Deliverables**

- Add in-app intake review and correction with original values preserved in an audit trail.
- Supply clearly labeled synthetic employees, receipts, expense reports, bank rows, emails, and security records.
- Test the AI Security Analyst golden rule: unknown stays unknown, conflicts are surfaced, every answer cites evidence, and follow-ups are prioritized.
- Test persistent chat memory, user corrections, questionnaire completion, and multi-source provenance.
- Write a short, repeatable judge demo covering risk/compliance and bookkeeping overspend detection.

**Acceptance checks**

- Editing an intake record records who/when/why and retains the original.
- Synthetic data is visibly labeled and cannot be confused with live company data.
- The demo includes at least one supported answer, one conflict, one unknown, one reconciliation, and one overspending suggestion.
- Automated tests and a manual click-through checklist both pass before merge.

## Merge order

1. Merge bank/reconciliation backend contracts.
2. Rebase and merge the visual work against those API contracts.
3. Merge demo/QA fixtures last, run the full suite, and complete the manual browser checklist.

Do not commit credentials, `.env` files, bank tokens, real statements, or customer documents. Use only the labeled synthetic fixtures in pull requests.
