# PayProof Atlas

**Evidence before action for small-business finance and risk teams.**

PayProof Atlas is a local-first financial evidence workspace built for the AI x Finance hackathon. It brings bank activity, receipts, approved email evidence, employee intake, and security records into one inspectable view so a human can understand what changed before making a consequential decision.

The default experience is a credential-free synthetic demo. Live Gmail, Plaid, model, and PRISM integrations are optional and remain visibly unconfigured until their server-side requirements are present.

## The problem

Small teams often investigate financial questions across a bank portal, inbox, receipts, spreadsheets, and intake folders. That fragmentation makes it easy to miss a changed payment destination, duplicate charge, missing receipt, control failure, or sudden spending increase. A general-purpose AI can make the situation worse if it guesses a category or presents a plausible explanation without showing its evidence.

## The solution

PayProof preserves each source, calculates findings with deterministic code, suggests explainable links between records, and gives the assistant only a bounded evidence packet. Users can inspect the underlying records, correct intake data through a versioned workflow, and record a review decision without allowing the model to move money.

> **Golden Rule:** Evidence may inform a decision. It never authorizes one.

## Key features

- **Interactive evidence atlas:** Explore controls, transactions, vendors, records, and their relationships in a depth-aware canvas view. Select a control or node to inspect its source context.
- **Evidence-backed spending guidance:** Compare recent spending with prior periods and surface possible cuts or overspending. An Amazon merchant name alone is not treated as proof of food, drinks, or any other category; categorization requires explicit receipt, email, or intake evidence.
- **Bank and evidence reconciliation:** Keep bank rows separate from bookkeeping totals, then suggest matches to invoices, receipts, email, and employee expenses using amount, currency, date, merchant, and references. Suggestions are never silently confirmed.
- **Multi-company source assignment:** Create and select company workspaces, then attach bank connections, Gmail authorization, and intake folders to the intended company. Workspace-scoped identities prevent the same provider record ID from overwriting another company's record.
- **Two bank-data paths:** Preview and import local CSV, OFX, or QFX statements without provider credentials, or optionally connect through Plaid Link for incremental transaction sync.
- **Read-only email evidence:** Optionally connect Gmail with read-only OAuth and import selected metadata and short snippets. Full message bodies and attachments are not imported.
- **Editable, auditable intake:** Assign structured JSON intake folders to a company. Corrections require a reason and preserve the original record plus every later version.
- **Risk and compliance workflow:** Answer a seven-control security questionnaire from source files, flag conflicts and gaps, and return `Unknown` when the evidence does not support a claim.
- **Bounded AI assistance:** Deterministic Python owns calculations and findings. An optional OpenAI-compatible model may only reword the grounded result; validation rejects changed amounts, currencies, evidence IDs, uncertainty, or assurance claims.
- **Human-controlled lifecycle:** Holds and reviews are simulated local audit events. Source removal and provider disconnects show impact before confirmation, preserve upstream records, and expose recovery states truthfully.

## How it works

```text
Approved source
  -> preview and validate
  -> preserve provenance in a workspace-scoped local store
  -> reconcile and calculate with deterministic rules
  -> optionally reword a bounded result with a model
  -> show evidence to a human for review and audit
```

Bank transactions remain separate from internal bookkeeping transactions, preventing a reconciled record from being counted twice. Imported document text is treated as untrusted evidence, not as an instruction or authorization.

## Tech stack

| Layer | Technology |
|---|---|
| Interface | HTML5, CSS, Canvas, and vanilla JavaScript |
| Local API | Python 3 and Flask |
| Data | SQLite plus bounded local JSON state |
| OCR | RapidOCR and ONNX Runtime |
| Assistant | Deterministic Python with an optional OpenAI-compatible Chat Completions endpoint |
| Integrations | Plaid Link, Gmail API read-only OAuth, and Block Convey PRISM tracing |
| Credential protection | Windows DPAPI for the current OS user; no plaintext fallback |

## Quick start

### Recommended Windows path

Requirements: Windows 10/11, Python 3 with the `py` launcher, and internet access during first-time dependency installation.

1. Double-click `Setup PayProof.cmd` once.
2. Double-click `Start PayProof.cmd`.
3. Keep the terminal window open. The browser opens after `/api/health` reports ready.

The app runs at <http://127.0.0.1:8765>. No provider account or API key is needed for the synthetic demo.

### Manual PowerShell setup

```powershell
cd C:\path\to\PayProof
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

Do not commit `.env`, OAuth client files, protected tokens, runtime databases, imported statements, or intake records.

## Optional live integrations

Copy `.env.example` to `.env`, then configure only the integrations you intend to demonstrate.

| Integration | Setup requirement | Honest fallback |
|---|---|---|
| Plaid | Server-side `PLAID_CLIENT_ID`, `PLAID_SECRET`, and `PLAID_ENV`; OAuth institutions also require an allowlisted HTTPS `PLAID_REDIRECT_URI` | Local CSV/OFX/QFX import remains available; status says not configured |
| Gmail | Google Desktop OAuth client JSON named `credentials.json` in the project root | Gmail controls remain disabled; other evidence paths continue working |
| Runtime model | `PAYPROOF_MODEL_BASE_URL`, `PAYPROOF_MODEL_API_KEY`, and `PAYPROOF_MODEL` | Deterministic local answers remain available and show fallback status |
| PRISM | `PRISMTRACE_HOST`, `PRISMTRACE_PROJECT_ID`, and `PRISMTRACE_API_KEY` | Status says not configured; failed configured deliveries are queued locally rather than reported as accepted |

Live Plaid and Gmail connections require Windows DPAPI support. PayProof never asks for a bank username or password, never returns a Plaid access token to the browser, and refuses plaintext token storage. Provider calls in the automated suite are mocked unless a result is explicitly labeled Live.

## Using company workspaces and your own records

1. Create or select the intended company workspace before adding a source.
2. Open **Sources & settings**. Bank, Gmail, imported files, and intake folders are managed for the active workspace only.
3. For a local bank statement, choose CSV, OFX, or QFX, inspect the accepted/rejected rows and suggested matches, then confirm the short-lived preview.
4. For Gmail, add the OAuth client file, connect the active workspace, then import only the matching messages you choose.
5. For intake, assign a dedicated folder containing structured expense JSON and run a scan. Use the supplied `/api/templates/intake.json` response as the field template.
6. To correct an imported expense, use **Edit & history**, explain the change, and save a new version. Editing the original file cannot silently replace an imported record.

Different currencies remain separate unless an explicit exchange-rate source exists. Reconciliation and spending-cut results are suggestions for human review, not accounting entries or payment instructions.

## Safety boundaries

- PayProof does not initiate payments, approve expenses automatically, or contact vendors.
- A changed destination or unusual purchase is an anomaly to verify, not proof of fraud.
- Unsupported security or financial claims remain `Unknown` and identify the next evidence needed.
- Imported content cannot override application controls or authorize an action.
- Gmail access is read-only, and imported snippets can be removed separately from OAuth disconnection.
- Plaid and Gmail disconnects require a fresh, session-bound impact preview and explicit confirmation.
- Removing a local source never claims to delete data at the bank or Gmail.
- Reset restores only synthetic demo review state and preserves user imports, chat history, corrections, bank records, and audit events.

## Tests and judge demo

Run the complete automated suite:

```powershell
Test PayProof.cmd
```

or:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers isolated databases, malformed and duplicate imports, workspace collisions, model-grounding failures, prompt injection, OAuth/token safety, provider failure recovery, reconciliation, correction history, reset preservation, and launcher readiness. Final browser acceptance remains a separate manual gate; see [the acceptance matrix](docs/QA_ACCEPTANCE.md).

For a concise recorded walkthrough, use the [60-90 second demo script](docs/DEMO_SCRIPT.md).

## Synthetic-data disclosure

Everything visible on first launch is fictional. Meridian Works, Personal Example, vendors, employees, invoices, transactions, account masks, email-like messages, security evidence, questionnaire answers, dates, and amounts are synthetic test fixtures. Example addresses use reserved or non-deliverable domains where applicable.

The repository contains no live provider credentials, bank login details, real Gmail tokens, customer financial records, or production compliance evidence. Mocked provider tests prove application behavior, not a live institution connection. PayProof is a hackathon prototype and does not provide financial, legal, audit, or compliance advice.

## Project documentation

- [Program overview](PROGRAM_OVERVIEW.md)
- [Timed demo script](docs/DEMO_SCRIPT.md)
- [QA acceptance matrix](docs/QA_ACCEPTANCE.md)
- [Prior-work reuse disclosure](REUSE_DISCLOSURE.md)
