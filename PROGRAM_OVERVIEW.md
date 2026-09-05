# PayProof Atlas program overview

## What PayProof is

PayProof Atlas is a local-first small-business money-operations assistant with an evidence-grounded trust and risk layer. It helps an owner understand money coming in and going out, reconcile records from different sources, find possible duplicate or unusual spending, complete evidence-backed questionnaires, and investigate before taking action.

PayProof does not initiate payments, approve expenses automatically, contact vendors, or treat an AI response as a source of truth.

## Core workflow

1. Create or select a company workspace, then collect its records from a bank feed, an uploaded CSV/OFX/QFX statement, read-only Gmail metadata, uploaded receipts, and assigned local intake folders.
2. Preserve each source separately with its source identity and provenance.
3. Normalize financial fields without silently inventing missing currencies, categories, account numbers, or dates.
4. Suggest explainable matches between bank transactions, invoices, receipts, emails, and employee expense reports.
5. Calculate totals, trends, anomalies, possible duplicates, and possible spending cuts with deterministic code.
6. Let the user inspect the supporting records, correct intake data with a reason, or mark a finding for human review.
7. Use an optional language model only to reword an already-calculated answer. A fail-closed validator rejects model text that changes amounts, evidence IDs, currencies, uncertainty, conflicts, or assurance claims.

## Bank connections

PayProof supports two bank-data paths:

- **Plaid Link:** the user authenticates inside Plaid's bank window. PayProof receives a revocable Plaid token, never the online-banking password. Tokens are protected for the current Windows user. Transactions are synchronized incrementally and stored with masked account identifiers.
- **Statement import:** CSV, OFX, and QFX files are parsed into a preview. Nothing is committed until the user reviews and confirms the accepted records.

Live Plaid status must be truthful: `not_configured`, `available`, `connected`, a specific recovery state, or an explicit error. Sandbox is used before any production bank connection.

## Email and intake

Gmail uses read-only OAuth and imports only selected message metadata and short snippets. It does not import full message bodies or attachments. OAuth tokens are workspace-bound, protected at rest, and revoked before a connection is reported as removed. Previously imported evidence is preserved unless the user separately previews and confirms its deletion.

The local `intake` folder accepts structured employee expense JSON. An imported record cannot be silently replaced by changing its original file. Corrections require an explanation and create a new version while preserving the original values, time, source, and changed fields.

## Reconciliation and spending guidance

Bank rows remain separate from internal bookkeeping transactions so the same spending is not counted twice. Suggested reconciliation uses fields such as amount, currency, date, merchant, reference, and linked source identifiers. A suggestion is not an automatic confirmation.

Spending-cut suggestions expose their calculation and cited transactions. Merchant identity alone does not prove what was purchased. For example, an Amazon transaction remains unitemized unless a receipt, email, or intake record explicitly identifies food, drinks, office supplies, or another category.

## Assurance and questionnaire workflow

The security questionnaire and company evidence are read from files rather than encoded as fixed answers. The deterministic assessor:

- hashes original source bytes;
- records filenames, dates, line numbers or JSON paths, and short excerpts;
- finds relevant evidence before asking a follow-up;
- labels answers `supported`, `partial`, `conflict`, or `unknown`;
- gives a targeted follow-up for missing or conflicting information;
- quarantines document text that attempts to instruct the assistant;
- never cites unreadable, oversized, unsupported, or unresolved material.

The included Meridian Works packet is synthetic and intentionally contains supported, partial, and conflicting outcomes. Unsupported questions such as an unprovided certification remain Unknown.

## User interface

The control-room dashboard keeps primary work inside a fixed-height workspace with drill-down drawers instead of a long page. The central graph relates financial or assurance objects. Status cards, nodes, evidence summaries, and connections open focused filters or details. Workspace controls create, rename, and select custom companies; Settings manages each active workspace's bank, Gmail, local files, intake folders, source removal, and intake corrections.

## Data and security boundaries

- Real secrets belong only in the ignored local `.env` or protected runtime storage.
- `.env`, OAuth client files, tokens, runtime databases, imported statements, intake records, and trace queues are excluded from Git.
- Bank and email removal require an impact preview and explicit confirmation.
- Every registered company workspace carries its own identity through bank connections, Gmail authorization and evidence, statement imports, intake folders, reconciliation, chat, and audit. Identical upstream record IDs cannot overwrite another workspace's records.
- Synthetic reset restores demo review state without deleting user imports, chat, corrections, audit history, or bank records.
- Imported content is evidence, never an instruction and never authorization to invoke an action.

## Included synthetic demonstration

The repository includes fictional:

- business and personal transactions;
- invoices, receipts, vendors, and payment destinations;
- four employee expense reports across three fictional employees;
- bank-like statement rows and reconciliation examples;
- Gmail-like metadata, including an adversarial message;
- a seven-question security questionnaire and eight evidence documents.

The demo includes a changed payment destination, duplicate invoice, missing receipt, new vendor, unusual Amazon spending, employee paperwork requiring review, failed backups, MFA exceptions, incomplete system coverage, and an offboarding conflict.

## Verification standard

Approval requires more than happy-path unit tests. PayProof is tested for malformed imports, duplicate sources, cross-workspace collisions, concurrency, network and persistence failures, token protection and revocation, model hallucination attempts, prompt injection, unknown claims, correction history, reset preservation, browser interactions, JavaScript errors, launcher readiness, and desktop-shortcut targeting.

Mocked provider tests are labeled Mocked. Only an actual successful provider response may be labeled Live.
