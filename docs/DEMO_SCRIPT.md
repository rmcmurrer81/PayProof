# PayProof Atlas: 80-second judge demo

## Pitch objective

Show that PayProof turns scattered small-business records into reviewable evidence without guessing or moving money. The three proof points are a control conflict, an itemized bank/email match, and a useful spending suggestion inside a strict company boundary.

## Preflight

- [ ] Run `Start PayProof.cmd`; start recording only after the dashboard loads.
- [ ] Use the bundled fictional data. No live account is required.
- [ ] Start in **Meridian Works** with the Atlas visible and drawers closed.
- [ ] Confirm **Personal Example** appears in the company picker.
- [ ] Rehearse asking: `What did the $43.57 Amazon bank transaction buy?`
- [ ] Leave **LOCAL FALLBACK** or **NEEDS KEY** visible when the runtime model or PRISM is not configured.
- [ ] Never label a mocked connector test as Live.

## Timed script

| Time | On screen | Say |
|---|---|---|
| 0–8 sec | Meridian Works evidence atlas | “Small businesses investigate money and risk across bank portals, inboxes, receipts, and intake folders. PayProof brings those records into one evidence workspace before anyone acts.” |
| 8–21 sec | Click **Are backups current?** | “Here, policy requires daily backups, but operating evidence shows failed jobs. PayProof reports the conflict, cites both sources, and asks for the missing restore evidence instead of inventing compliance.” |
| 21–39 sec | Switch to **Personal Example**; ask **What did the $43.57 Amazon bank transaction buy?** | “This bank row and email agree on exact amount, currency, date, merchant, and order reference. Only then does PayProof show the email’s explicit items—coffee filters and sparkling water—with both evidence IDs. If two emails tie, it says ambiguous and withholds the items.” |
| 39–53 sec | Ask **Where could I cut spending?** | “PayProof compares the latest 30 days with the prior monthly baseline and suggests a possible cut. It keeps the calculation visible and calls it a review suggestion, not a conclusion.” |
| 53–69 sec | Open **Sources**; point to company manager and connector sections | “Each company has its own website, logo, banks, read-only Gmail evidence, and custom intake folders. Switching companies changes the dashboard and the assistant’s evidence boundary. A closed company is safely archived, with records preserved for restore.” |
| 69–80 sec | Return to the atlas or leave Sources open | “The Golden Rule is simple: evidence may inform a decision, but it never authorizes one. PayProof does not move money—it gives the human a defensible next step and an audit trail.” |

## Presenter cues

- Keep the cursor near the evidence being discussed; do not tour every control.
- Let the assistant finish before pointing to its evidence IDs.
- Say **conflict**, **anomaly**, **ambiguous**, or **suggestion**. Do not say **fraud**, **approved**, or **compliant** unless the displayed evidence supports it.
- Identify the default companies, emails, transactions, employees, and security records as synthetic.
- If the model badge says **LOCAL FALLBACK**, say deterministic answers remain available without a model endpoint.
- If PRISM says **NEEDS KEY**, say live trace delivery requires configured credentials. Do not imply a trace was accepted.
- Do not open Plaid Link or Gmail OAuth during the timed pitch unless that exact sandbox/test flow was verified immediately beforehand.

## Optional transfer extension

Use only if the recording remains under 90 seconds and the transfer control is present in the tested build: open the company transfer preview and say, “If the business is sold, the owner can download its paperwork as ordinary HTML, CSV, and JSON with a SHA-256 manifest. The buyer can read it in a browser without installing PayProof, and credentials are excluded.”

## Recovery lines

- **Provider not configured:** “The connector is disabled until server credentials and protected token storage are present; local statement import still works.”
- **Model unavailable:** “PayProof keeps the deterministic answer and labels the fallback instead of hiding the failure.”
- **PRISM unavailable:** “The UI does not claim acceptance; a configured failed delivery is queued locally for retry.”
- **Short on time:** Skip the spending question and move from the $43.57 match to Sources, then close.

## Final recording gate

- [ ] Duration is 60–90 seconds.
- [ ] The bundled data is called synthetic.
- [ ] A conflict and its citations are visible.
- [ ] The $43.57 match shows both bank and email evidence and remains review-required.
- [ ] The spending suggestion includes a baseline and uncertainty.
- [ ] Company-scoped sources and reversible archive behavior are stated.
- [ ] No live model, connector, or PRISM claim is made without a verified response.
- [ ] The close says PayProof does not move money.
