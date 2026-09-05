# PayProof Atlas acceptance matrix

This is the release gate for the Money Operations and Intake/Assurance workflows. “Automated pass” means the isolated current-code test named in **Recorded evidence** passed on 2026-09-05. Browser, launcher, and live-provider checks remain separate and must not be inferred from unit tests.

## Recorded evidence

| Evidence | Current result |
|---|---|
| `tests.test_ai_conversation`, `tests.test_email_bank_enrichment`, and `tests.test_company_profile` | **PASS — 23/23 tests** |
| `tests.test_company_transfer` and `tests.test_company_transfer_api` | **PASS — 11/11 builder and API tests**; confirmation, active/archived exports, portable contents, safe headers, isolation, audit, and credential non-leakage |
| `tools/ai_conversation_eval.py` | **PASS — 50/50 deterministic machine checks** |
| Bounded qualitative assistant rubric | **10/10 heuristic**; not a scientifically valid Turing test and not a consciousness claim |
| Full repository test discovery after final UI/transfer merge | **Pending final run** |
| Browser and desktop-launcher acceptance | **Pending final run** |

The conversation harness runs against temporary synthetic data with network-backed model and trace integrations disabled. It checks the deterministic fallback, not the quality or availability of an external model service.

## Company identity, isolation, and lifecycle

| Check | Expected result | Status |
|---|---|---|
| Create and edit company profile | Name and validated HTTP(S) website persist for that company | Automated pass |
| Upload company logo | PNG, JPEG, or WebP content is signature-checked, limited to 2 MB, served same-origin with safe headers, and not exposed as a filesystem path | Automated pass |
| Switch companies | Dashboard, chat context, banks, Gmail evidence, intake folders, reconciliation, and audit data change to the selected company | Automated pass; browser pending |
| Same provider ID in two companies | One company cannot overwrite or read the other company's record | Automated pass |
| Remove a closed company | Exact-name confirmation archives it from active use; financial records, branding, connector assignments, and history remain preserved | Automated pass; browser pending |
| Restore archived company | Explicit confirmation returns it to the active selector with preserved records | Automated pass; browser pending |
| Protect demo workspaces | Built-in synthetic workspaces cannot be archived or rebranded | Automated pass |
| Export transfer package | Buyer receives browser-readable HTML plus Excel/Sheets-safe CSV and JSON, a reading guide, and a SHA-256/byte-count manifest; credentials, protected tokens, logo/raw intake files, connector stores, and local paths are excluded | Automated pass; browser download pending |
| Transfer confirmation and audit | Custom or archived company only; exact company name and explicit confirmation are required; generation records an audit event without removing PayProof records | Automated pass; browser pending |
| Transfer safety limits | Credential-shaped text is redacted, spreadsheet formulas are neutralized, and row/byte limits fail instead of silently truncating | Builder automated pass |

## Bank, email, and intake reconciliation

| Check | Expected result | Status |
|---|---|---|
| Bank statement preview | Accepted and rejected CSV/OFX/QFX rows appear before any write | Covered; full suite rerun pending |
| Exact $43.57 Amazon match | Bank and email agree on amount, USD currency, date, merchant, and order reference; explicit coffee-filter and sparkling-water items appear with both evidence IDs | Automated pass |
| Ambiguous email match | Equal top candidates produce `ambiguous`; PayProof withholds item details and asks for review | Automated pass |
| Amount substring or wrong currency | `$43.57` does not match `$143.57`, and USD evidence does not match a EUR row | Automated pass |
| Cross-company itemization | An email from Company A cannot enrich Company B's bank transaction | Automated pass |
| Probable match | Every contributing rule is visible; the score is described as a rule score, not a probability | Covered; browser pending |
| Unmatched bank row | Row remains unmatched and names the missing receipt/email/intake evidence | Covered; browser pending |
| Refund or credit | Direction remains explicit and does not inflate spending | Machine-check pass |
| Multiple currencies | Totals remain separate without an explicit exchange-rate source | Covered; full suite rerun pending |
| Vendor spending spike | Suggestion names period, baseline, cited transactions, category uncertainty, and that it is not a conclusion | Machine-check pass |

## Editable intake and provenance

| Check | Expected result | Status |
|---|---|---|
| Assign custom folders/subfolders | Folder belongs only to the active company; recursive scanning follows its explicit setting | Covered; browser pending |
| Correct an expense | Before/after values, reason, time, and source ID are retained | Machine-check pass |
| Scan a changed file with an existing ID | No silent overwrite; the user is directed to audited correction | Covered; full suite rerun pending |
| Open correction history | Original import and every later version remain available | Machine-check pass; browser pending |
| Malicious document instruction | Content remains untrusted evidence and no state-changing action runs | Machine-check pass |

## Risk and Compliance Track — AI Security Analyst

| Check | Expected result | Status |
|---|---|---|
| Supported control | Answer cites resolvable source IDs, excerpts, dates, and SHA-256 digests | Machine-check pass |
| Unsupported control | Starts with Unknown and asks the smallest useful follow-up | Machine-check pass |
| Conflicting sources | Shows both sources, conflict status, and a targeted follow-up | Machine-check pass |
| Questionnaire import | Questions come from the loaded questionnaire rather than a fixed answer list | Covered; full suite rerun pending |
| Evidence replacement | Re-ingestion changes the derived answer without a code edit | Covered; full suite rerun pending |
| Model rewrite guard | Optional model text cannot introduce uncited claims, drop uncertainty, or replace deterministic numbers | Covered; full suite rerun pending |
| Persistent follow-up | A bare same-session “Why?” uses the last cited control after reload without needing a client-supplied selection | Automated pass |
| Company-scoped memory | Chat context and history do not cross company boundaries and chat is never promoted to company evidence | Automated pass |
| Corrected financial state | After an audited correction, the assistant does not repeat the stale expense-review claim | Machine-check pass |

## Data safety, connectors, and reset

| Check | Expected result | Status |
|---|---|---|
| Isolated automated tests | Temporary database and runtime folders leave user imports and chat unchanged | Automated pass for focused suites |
| Reset synthetic example | Demo review state resets while imported sources, corrections, bank rows, chat, and audit events remain | Covered; full suite rerun pending |
| Clean clone without credentials | Dashboard, deterministic assistant, imports, and tests work; connectors and PRISM say Not configured | Manual pending |
| Re-import same bank statement | No duplicate transaction is created | Covered; full suite rerun pending |
| Plaid and Gmail secrets | Bank credentials never enter PayProof; provider tokens remain server-side and use Windows DPAPI with no plaintext fallback | Covered; live check optional |
| Connector removal | Fresh session-bound impact preview and confirmation are required; preserved upstream/imported data is described truthfully | Covered; browser pending |

## Browser, launcher, and presentation

| Check | Expected result | Status |
|---|---|---|
| Desktop shortcut | Opens the repository's real `Start PayProof.cmd` target | Pending final run |
| Launcher readiness | Browser opens only after `/api/health` reports ready | Pending final run |
| Laptop viewport | No whole-page vertical scroll or clipped critical controls at 1366×768 | Pending final run |
| Clickable status and graph controls | Cards, nodes, summaries, and company controls open the correct focused details | Pending final run |
| Company profile and archive UI | Website/logo changes, exact-name archive confirmation, archived list, and restore work end to end | Pending final run |
| Console/network check | No uncaught errors; unconfigured connectors and PRISM are explained rather than reported as successful | Pending final run |
| GitHub README and video | README covers the problem, solution, features, stack, operation, setup, tests, transfer portability, and disclosure; video is 60–90 seconds | README ready; recording pending |

## Required judge demonstration

The 60–90 second recording should visibly demonstrate:

1. A cited control conflict or honest Unknown.
2. The $43.57 Amazon bank/email match with explicit itemization and review-required language.
3. An evidence-backed overspending suggestion with its calculation and uncertainty.
4. Company-scoped source management and reversible archive behavior.
5. The Golden Rule: PayProof does not move money or treat evidence as authorization.

Do not mark a browser row Passed until the exact submitted build is exercised. Mocked provider tests must be labeled **Mocked**; only a successful real provider response may be labeled **Live**. A missing PRISM key must remain visibly unconfigured, never described as an accepted trace.
