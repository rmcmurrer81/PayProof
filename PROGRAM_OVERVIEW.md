# PayProof Atlas program overview

## What PayProof is

PayProof Atlas is a local-first small-business money-operations assistant with an evidence-grounded trust and risk layer. It helps an owner understand money coming in and going out, reconcile records from different sources, find possible duplicate or unusual spending, complete evidence-backed questionnaires, and investigate before taking action.

PayProof does not initiate payments, approve expenses automatically, contact vendors, or treat an AI response as a source of truth.

## Core workflow

1. Create or select a company workspace with its name, website, and optional validated logo, then collect its records from a bank feed, an uploaded CSV/OFX/QFX statement, read-only Gmail metadata, uploaded receipts, and assigned local intake folders or subfolders.
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

Bank rows remain separate from internal bookkeeping transactions so the same spending is not counted twice. Suggested reconciliation uses fields such as amount, currency, date, merchant, reference, and linked source identifiers. A suggestion is not an automatic confirmation, and its rule score is not presented as a probability.

The bundled synthetic example includes a $43.57 Amazon bank transaction and email receipt. PayProof links them because the exact amount and USD currency, date, normalized merchant, and order reference agree. It then displays only the items explicitly present in the email—coffee filters and sparkling water—and cites both the bank and email records. If another email ties for the top match, the result becomes ambiguous and the items remain unknown until a person resolves it.

Spending-cut suggestions expose their calculation and cited transactions. Merchant identity alone does not prove what was purchased. An Amazon transaction remains unitemized unless a receipt, email, or intake record explicitly identifies food, drinks, office supplies, or another category.

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

The control-room dashboard keeps primary work inside a fixed-height workspace with drill-down drawers instead of a long page. The central depth-aware graph relates financial or assurance objects. Status cards, nodes, evidence summaries, and connections open focused filters or details. Workspace controls create, rename, brand, archive, restore, and select custom companies; Settings manages each active workspace's bank, Gmail, local files, intake folders, source removal, and intake corrections.

## Company boundaries and lifecycle

Every company has a separate dashboard context, source inventory, bank connections, Gmail authorization, intake folders, reconciliation results, corrections, chat history, and audit trail. Switching from Company A to Company B therefore changes both the visible records and the assistant's evidence boundary.

Removing a closed company is implemented as a reversible archive, not destructive deletion. It requires explicit confirmation plus the exact company name, hides the company from the active picker, and preserves its records and connector assignments. Restore also requires explicit confirmation. The built-in synthetic workspaces cannot be archived.

Company-scoped conversation context is persisted in SQLite. A bare same-session follow-up such as “Why?” can resolve to the last cited control after a reload, but that history is not promoted into company evidence and is never reused across company boundaries.

## Portable sale or ownership transfer

A custom company, including an archived company, can produce a read-only transfer ZIP after explicit confirmation and exact-name entry. This does not remove records from PayProof or transfer any live bank or Gmail authorization. It creates ordinary files that a buyer can open without the program:

- a self-contained `index.html` with company profile, record counts, currency/type totals, and readable record tables;
- Excel/Google Sheets-safe CSV and JSON copies of allowlisted company records;
- `company-profile.json` and a plain-text reading guide;
- `manifest.json` with the company identity, generation time, file byte counts, and SHA-256 digest for every payload file.

The data copies cover company-scoped vendors, ledger and bank transactions, invoices, receipts, employees and expense reports, email evidence, intake document metadata and correction history, reconciliations, imports, and audit events.

The exporter is intentionally single-company and allowlist-based. It excludes `.env`, API keys, protected bank/email tokens, connector runtime stores, company logo files, local filesystem paths, and raw intake-folder files. Credential-shaped text inside an otherwise exportable record is redacted, spreadsheet formula-like cells are neutralized, and row/size limits fail closed instead of silently producing an incomplete package. Generating a package adds an audit event. The recipient uses their own authorization if they later connect accounts to another system.

## Data and security boundaries

- Real secrets belong only in the ignored local `.env` or protected runtime storage.
- `.env`, OAuth client files, tokens, runtime databases, imported statements, intake records, and trace queues are excluded from Git.
- Bank and email removal require an impact preview and explicit confirmation.
- Every registered company workspace carries its own identity through bank connections, Gmail authorization and evidence, statement imports, intake folders, reconciliation, chat, and audit. Identical upstream record IDs cannot overwrite another workspace's records.
- Company archive/restore preserves financial records and source assignments while preventing an accidental irreversible deletion.
- Portable company transfer is a credential-free copy for review or migration; it does not change ownership, move money, or grant access to a provider account.
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

The dedicated synthetic assistant evaluation currently passes 50/50 deterministic machine checks plus a 10/10 qualitative heuristic for naturalness, follow-up relevance, epistemic calibration, consistency, and actionability. That rubric is a repeatable release check, **not a scientifically valid Turing test** and not a claim of consciousness.

Mocked provider tests are labeled Mocked. Only an actual successful provider response may be labeled Live.
