# PayProof Atlas

**Evidence before action for small-business finance and risk teams.**

PayProof Atlas is a local-first bookkeeping and risk assistant built for the AI x Finance hackathon. It brings bank activity, receipts, approved email evidence, employee intake, and security records into one readable workspace so a small-business owner can see money coming in and going out, understand what changed, and inspect the proof before making a consequential decision.

[GitHub repository](https://github.com/rmcmurrer81/PayProof) · shared submission branch: `main`

The default experience is a credential-free synthetic demo. Live Gmail, Plaid, Tavily, model, and PRISM integrations are optional and remain visibly unconfigured until their server-side requirements are present.

## The problem

Small teams often investigate financial questions across a bank portal, inbox, receipts, spreadsheets, and intake folders. That fragmentation makes it easy to miss a changed payment destination, duplicate charge, missing receipt, control failure, or sudden spending increase. A general-purpose AI can make the situation worse if it guesses a category or presents a plausible explanation without showing its evidence.

## The solution

PayProof preserves each source, calculates findings with deterministic code, suggests explainable links between records, and gives the assistant only a bounded evidence packet. Users can inspect the underlying records, correct intake data through a versioned workflow, and record a review decision without allowing the model to move money.

> **Golden Rule:** Evidence may inform a decision. It never authorizes one.

## Key features

- **Readable, live dashboard:** Large plain-language sections, clickable status cards, expandable detail panels, a company picker, and visible last/next refresh status make the interface usable without technical training. The page stays within the desktop viewport while focused panels hold the detail.
- **Interactive evidence atlas:** Explore controls, transactions, vendors, employees, records, and their relationships in a depth-aware 3D canvas. The coverage view adds a dimensional North America map with clickable evidence locations; selecting a card, node, person, or location opens its source context.
- **People & Spending:** See employee names, report counts, total reported spend, missing receipts, and items needing review for the active company, then expand one person or report for evidence.
- **Evidence-backed spending guidance:** Compare recent spending with prior periods and surface possible cuts or overspending. Merchant identity alone is never treated as proof of what was purchased; categorization requires explicit receipt, email, or intake evidence.
- **Explainable bank/email matching:** A synthetic $43.57 Amazon bank row is linked to an email only because amount, USD currency, date, merchant, and order reference agree. The email supplies the explicit items—coffee filters and sparkling water—and both records remain cited. A tied candidate is marked ambiguous, never silently chosen.
- **Bank and evidence reconciliation:** Keep bank rows separate from bookkeeping totals, then suggest matches to invoices, receipts, email, and employee expenses using amount, currency, date, merchant, and references. Every suggestion requires human review and the score is not presented as a probability.
- **Multi-company source assignment:** Create and select company workspaces with a name, website, and validated PNG/JPEG/WebP logo, then attach bank connections, Gmail authorization, and one or more intake folders or subfolders to the intended company. Workspace-scoped identities prevent the same provider record ID from overwriting another company's record.
- **Two bank-data paths:** Preview and import local CSV, OFX, or QFX statements without provider credentials, or optionally connect through Plaid Link for incremental transaction sync.
- **Read-only email evidence:** Optionally connect Gmail with read-only OAuth and import selected metadata and short snippets. Full message bodies and attachments are not imported.
- **Editable, auditable intake:** Assign structured JSON intake folders to a company. Corrections require a reason and preserve the original record plus every later version.
- **Truthful source refresh:** Automatic refresh defaults to 5 minutes, with a 10-minute option. For the active company, PayProof rescans assigned intake folders and refreshes configured bank and Gmail sources, then shows elapsed time, the next refresh, and any source that needs attention. It never changes numbers just to look active.
- **Optional outside research:** A server-side Tavily connection can search the public web for a company or vendor and save bounded results as clearly marked **unverified leads**. Search rank is not proof, outside text is untrusted, and a web result never closes a finding by itself.
- **Risk and compliance workflow:** Answer a seven-control security questionnaire from source files, flag conflicts and gaps, and return `Unknown` when the evidence does not support a claim.
- **Bounded AI assistance:** Deterministic Python owns calculations and findings. An optional OpenAI-compatible model may only reword the grounded result; validation rejects changed amounts, currencies, evidence IDs, uncertainty, or assurance claims.
- **Company-scoped conversational memory:** A same-session follow-up such as “Why?” resolves against the last cited control for that company. History persists across reloads without becoming company evidence and never carries into a different company workspace.
- **Optional hands-free conversation:** Press the microphone to ask one question and, when the browser offers an eligible Natural, Neural, or Online voice, turn on spoken replies. Voice is opt-in, stops between questions, and falls back honestly to text instead of using a known robotic offline voice.
- **Human-controlled lifecycle:** Holds and reviews are simulated local audit events. Source removal and provider disconnects show impact before confirmation, preserve upstream records, and expose recovery states truthfully. Closing a company archives it only after exact-name confirmation; records and connector assignments are preserved for an explicit restore.
- **Portable company transfer:** After exact-name confirmation, a custom company—including an archived one—can be exported as a ZIP with a self-contained browser-readable `index.html`, Excel/Google Sheets-safe CSV files, JSON files, a plain-text guide, and a SHA-256/byte-count manifest. The recipient does not need PayProof to read it. Credentials, tokens, `.env`, logo files, raw intake-folder files, connector stores, and local paths are excluded; credential-shaped database text is redacted.

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
| Interface | HTML5, CSS, Canvas, SVG, vanilla JavaScript, and optional browser Speech Recognition/Synthesis |
| Local API | Python 3 and Flask |
| Data | SQLite plus bounded local JSON state |
| OCR | RapidOCR and ONNX Runtime |
| Assistant | Deterministic Python with an optional OpenAI-compatible Chat Completions endpoint |
| Integrations | Plaid Link, Gmail API read-only OAuth, optional Tavily Search API, and Block Convey PRISM tracing |
| Credential protection | Windows DPAPI for the current OS user; no plaintext fallback |

## Quick start

Clone the current shared build, or pull `main` if the repository is already present:

```powershell
git clone https://github.com/rmcmurrer81/PayProof.git
cd PayProof
# Existing clean checkout: git pull origin main
```

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
| Tavily public-web research | Server-side `TAVILY_API_KEY` | Outside research stays off; saved internal, bank, email, and intake evidence continues working |
| PRISM | `PRISMTRACE_HOST`, `PRISMTRACE_PROJECT_ID`, and `PRISMTRACE_API_KEY` | Status says not configured; failed configured deliveries are queued locally rather than reported as accepted |

Live Plaid and Gmail connections require Windows DPAPI support. PayProof never asks for a bank username or password, never returns a Plaid access token to the browser, and refuses plaintext token storage. Keep every API key in the server's `.env`; never paste one into the browser or commit it to GitHub. Provider calls in the automated suite are mocked unless a result is explicitly labeled Live.

## Using company workspaces and your own records

1. Create or select the intended company, then add its name, website, and optional logo.
2. Open **Sources & settings**. Bank, Gmail, imported files, and custom intake folders are managed for the active company only.
3. For a local bank statement, choose CSV, OFX, or QFX, inspect accepted/rejected rows and suggested matches, then confirm the short-lived preview.
4. For Gmail, add the OAuth client file, connect the active company, then import only the matching messages you choose.
5. For intake, assign one or more dedicated folders or subfolders containing structured expense JSON and run a scan. Use the supplied `/api/templates/intake.json` response as the field template.
6. To correct an imported expense, use **Edit & history**, explain the change, and save a new version. Editing the original file cannot silently replace an imported record.
7. If a company closes, use **Remove company**. This is a safe archive: exact-name confirmation removes it from the active picker while retaining records and connection assignments; an explicit restore makes it active again.
8. If the company is sold, generate its transfer package after reviewing the company name. The ZIP is a read-only copy for the buyer; it does not transfer bank/Gmail authorization or change the records retained in PayProof. The same operation is available at `POST /api/workspaces/<id>/transfer-package` with `{"confirm":true,"company_name":"Exact Company Name"}`.
9. Set **Auto refresh** to every 5 or 10 minutes. Only the currently selected company's configured online sources and assigned intake folders refresh. PayProof pauses while a drawer, authorization flow, chat request, or voice capture is active and reports partial failures instead of hiding them.
10. If Tavily is configured, use **Outside research** only for public company or vendor terms. The query is sent to Tavily, so never include account numbers, transaction amounts, private email addresses, or other confidential data. Review the returned page yourself before treating it as evidence.

Different currencies remain separate unless an explicit exchange-rate source exists. Reconciliation and spending-cut results are suggestions for human review, not accounting entries or payment instructions.

## Safety boundaries

- PayProof does not initiate payments, approve expenses automatically, or contact vendors.
- A changed destination or unusual purchase is an anomaly to verify, not proof of fraud.
- Unsupported security or financial claims remain `Unknown` and identify the next evidence needed.
- Imported content cannot override application controls or authorize an action.
- Public-web search is never automatic. Tavily queries run only when a person submits one, and every saved result remains an unverified, removable local lead until independently checked.
- Gmail access is read-only, and imported snippets can be removed separately from OAuth disconnection.
- Plaid and Gmail disconnects require a fresh, session-bound impact preview and explicit confirmation.
- Removing a local source never claims to delete data at the bank or Gmail.
- Archiving a company is intentionally reversible and does not erase its financial paperwork, corrections, chat, or source assignments.
- A transfer package exports only one allowlisted custom-company dataset, records an audit event, fails rather than silently truncating at its safety limits, and never includes connector credentials. A buyer must establish new bank and email authorization separately.
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

The suite covers isolated databases, malformed and duplicate imports, workspace collisions, model-grounding failures, prompt injection, OAuth/token safety, provider failure recovery, reconciliation, correction history, reset preservation, company archive/restore, transfer credential redaction, branding validation, bounded public-web imports, Tavily key/redirect/error safety, and launcher readiness. Tavily and other provider calls are mocked unless explicitly labeled Live. A dedicated synthetic conversation harness currently passes **50/50 machine checks** and a **10/10 bounded qualitative heuristic** covering financial math, itemized email matching, ambiguity, corrections, company isolation, unknown answers, prompt injection, and unassisted same-session follow-ups. This is explicitly **not a scientifically valid Turing test** and makes no claim of consciousness. Browser acceptance remains a separate gate; see [the acceptance matrix](docs/QA_ACCEPTANCE.md).

For a concise recorded walkthrough, use the [60-90 second demo script](docs/DEMO_SCRIPT.md).

## Synthetic-data disclosure

Everything visible on first launch is fictional. Meridian Works, Personal Example, vendors, employees, invoices, transactions, account masks, email-like messages, security evidence, questionnaire answers, dates, and amounts are synthetic test fixtures. Example addresses use reserved or non-deliverable domains where applicable.

The repository contains no live provider credentials, bank login details, real Gmail tokens, customer financial records, or production compliance evidence. Mocked provider tests prove application behavior, not a live institution connection. PayProof is a hackathon prototype and does not provide financial, legal, audit, or compliance advice.

## Project documentation

- [Program overview](PROGRAM_OVERVIEW.md)
- [Timed demo script](docs/DEMO_SCRIPT.md)
- [QA acceptance matrix](docs/QA_ACCEPTANCE.md)
- [Prior-work reuse disclosure](REUSE_DISCLOSURE.md)
