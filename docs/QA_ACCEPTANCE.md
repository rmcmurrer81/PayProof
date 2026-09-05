# PayProof Atlas acceptance matrix

This checklist is the shared approval gate for Tracks 2 and 3. A passing unit test is not enough when the browser workflow or source provenance is wrong. Record the final result and evidence after each check is run.

## Data safety and reset

| Check | Expected result | Status |
|---|---|---|
| Automated tests use an isolated temporary database | Runtime imports and chat history are unchanged | Pending |
| Reset synthetic example | Synthetic fixtures return to their baseline; imported sources and corrections remain | Pending |
| Clean clone without credentials | Dashboard, deterministic assistant, imports, and tests work; connectors say Not configured | Pending |
| Re-import same bank statement | No duplicate transaction is created | Pending |

## Bank, email, and intake reconciliation

| Check | Expected result | Status |
|---|---|---|
| Bank statement preview | Accepted and rejected rows are shown before any write | Pending |
| Exact match | One bank row matches one source record with explained fields | Pending |
| Probable match | Confidence and every contributing field are visible | Pending |
| Ambiguous match | No automatic assignment; candidate records and follow-up are shown | Pending |
| Unmatched bank row | Marked unmatched; missing receipt/email/intake evidence is named | Pending |
| Refund or credit | Direction remains explicit and does not inflate spending | Pending |
| Multiple currencies | Totals remain separate without an exchange-rate source | Pending |
| Vendor spending spike | Suggestion names period, baseline, transactions, category uncertainty, and that it is not a conclusion | Pending |

## Editable intake and provenance

| Check | Expected result | Status |
|---|---|---|
| Correct an expense | Before/after values, reason, time, and source ID are retained | Pending |
| Scan changed file with an existing ID | No 500 or silent overwrite; user is directed to audited correction | Pending |
| Open correction history | Original import and every later version remain available | Pending |
| Malicious document instruction | Treated as untrusted content; no state-changing action runs | Pending |

## Risk and Compliance Track — AI Security Analyst

| Check | Expected result | Status |
|---|---|---|
| Supported control | Answer cites resolvable source IDs, excerpts, dates, and SHA-256 digests | Pending |
| Unsupported control | Starts with Unknown and asks the smallest useful follow-up | Pending |
| Conflicting sources | Shows both sources, conflict status, and a targeted follow-up | Pending |
| Questionnaire import | Questions come from the uploaded questionnaire rather than a fixed list | Pending |
| Evidence replacement | Re-ingestion changes the derived answer without a code edit | Pending |
| Model rewrite | Cannot introduce uncited claims, drop uncertainty, or replace deterministic numbers | Pending |
| Persistent conversation | Reload retains visible history, but chat text is not promoted to company fact | Pending |

## Browser and launcher

| Check | Expected result | Status |
|---|---|---|
| Desktop shortcut | Opens the real `C:\Users\robmc\PayProof` application | Pending |
| Launcher readiness | Browser opens only after `/api/health` is ready | Pending |
| Laptop viewport | No whole-page vertical scroll or clipped critical controls at 1366x768 | Mike / Track 1 |
| Selection correctness | Evidence and review actions always target the visible selection | Mike / Track 1 |
| Console/network check | No uncaught errors; expected unconfigured connectors are explained | Pending |

## Required judge demonstration

The final two-minute walkthrough must visibly exercise all five outcomes:

1. A supported security answer with clickable evidence.
2. A conflict between written policy and observed operation.
3. An honest Unknown plus one prioritized follow-up.
4. A bank transaction reconciled to email, receipt, or employee intake paperwork.
5. An evidence-backed overspending suggestion with its calculation and uncertainty.

Do not mark a row Passed until the exact current build is exercised. Mocked connector tests must be labeled Mocked; only a successful real provider response may be labeled Live.
