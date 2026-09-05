# PayProof Atlas: 86-second judge demo

## Pitch objective

Show that PayProof turns scattered small-business records into reviewable evidence without guessing or moving money. The three proof points are a control conflict, an itemized bank/email match, and a useful spending suggestion inside a strict company boundary.

## Preflight

- [ ] Run `Start PayProof.cmd`; start recording only after the dashboard loads.
- [ ] Use the bundled fictional data. No live account is required.
- [ ] Start in **Meridian Works** with the Atlas visible and drawers closed.
- [ ] Confirm **Personal Example** appears in the company picker.
- [ ] Leave **Auto refresh** at 5 minutes and confirm the live status shows when data was actually loaded and when the next refresh is due.
- [ ] Rehearse asking: `What did the $43.57 Amazon bank transaction buy?`
- [ ] If demonstrating voice, verify the microphone and an eligible Natural/Neural/Online browser voice before recording. Otherwise type the question; do not spend pitch time troubleshooting permissions.
- [ ] Leave **LOCAL FALLBACK** or **NEEDS KEY** visible when the runtime model or PRISM is not configured.
- [ ] Leave Tavily visibly off when `TAVILY_API_KEY` is absent. Never run a live public-web search during the pitch unless it was tested immediately beforehand.
- [ ] Never label a mocked connector test as Live.

## Timed script

| Time | On screen | Say |
|---|---|---|
| 0–10 sec | Meridian Works dashboard; sweep across the clickable cards, 3D atlas, company picker, and live refresh label | “Small businesses chase answers across bank portals, inboxes, receipts, and intake folders. PayProof turns them into one readable, live evidence workspace.” |
| 10–22 sec | Click **Are backups current?** or the matching status card | “Policy requires daily backups, but operating records show failures. PayProof shows the conflict and sources, then asks for missing proof instead of guessing.” |
| 22–40 sec | Switch to **Personal Example**; ask **What did the $43.57 Amazon bank transaction buy?** by typing or the rehearsed mic | “The bank row and email agree on amount, currency, date, merchant, and order. Only then does PayProof add the email’s coffee filters and sparkling water, citing both records. A tie stays ambiguous.” |
| 40–54 sec | Ask **Where could I cut spending?**, then open **People & spending** | “PayProof compares the latest period with its baseline and offers a review suggestion—not a conclusion. People and Spending shows each employee, reported spend, missing receipts, and items needing review.” |
| 54–70 sec | Open **Sources & settings**; point to bank, Gmail, intake, refresh, and Outside research | “Each company has separate banks, read-only email, and intake folders. PayProof refreshes configured sources every five or ten minutes and reports failures. Public-web results are manual, unverified leads—not proof.” |
| 70–79 sec | Point to company archive/restore and transfer controls | “Closed companies can be archived and restored. If sold, their paperwork exports in browser-readable and spreadsheet formats without credentials.” |
| 79–86 sec | Return to the dashboard or assistant | “Evidence may inform a decision; it never authorizes one. PayProof never moves money. The human stays in control.” |

## Presenter cues

- Keep the cursor near the evidence being discussed; do not tour every control.
- Let the assistant finish before pointing to its evidence IDs.
- Say **conflict**, **anomaly**, **ambiguous**, or **suggestion**. Do not say **fraud**, **approved**, or **compliant** unless the displayed evidence supports it.
- Identify the default companies, emails, transactions, employees, and security records as synthetic.
- If the model badge says **LOCAL FALLBACK**, say deterministic answers remain available without a model endpoint.
- If PRISM says **NEEDS KEY**, say live trace delivery requires configured credentials. Do not imply a trace was accepted.
- If Tavily says **Not configured**, say public-web research is optional and server-side. Even when configured, results remain unverified until a person checks the source.
- The 5/10-minute refresh includes assigned intake folders and configured bank/Gmail sources for the active company. It does **not** run Tavily searches automatically.
- Voice is opt-in browser capability. Do not promise spoken replies when no eligible Natural, Neural, or Online voice is available.
- Do not open Plaid Link or Gmail OAuth during the timed pitch unless that exact sandbox/test flow was verified immediately beforehand.

## Recovery lines

- **Provider not configured:** “The connector is disabled until server credentials and protected token storage are present; local statement import still works.”
- **Model unavailable:** “PayProof keeps the deterministic answer and labels the fallback instead of hiding the failure.”
- **PRISM unavailable:** “The UI does not claim acceptance; a configured failed delivery is queued locally for retry.”
- **Tavily unavailable:** “Outside research stays off; the company’s saved evidence and findings continue working.”
- **Voice unavailable:** “The same grounded assistant remains available in text, without substituting a robotic offline voice.”
- **Short on time:** Skip the spending question and move from the $43.57 match to Sources, then close.

## Final recording gate

- [ ] Duration is 60–90 seconds.
- [ ] The bundled data is called synthetic.
- [ ] A conflict and its citations are visible.
- [ ] The $43.57 match shows both bank and email evidence and remains review-required.
- [ ] The spending suggestion includes a baseline and uncertainty.
- [ ] Company-scoped sources and reversible archive behavior are stated.
- [ ] The live refresh label is visible; no claim is made that static demo values are streaming from a provider.
- [ ] Tavily results, if shown, are called unverified leads and the search is described as manual.
- [ ] Voice, if shown, was verified in the recording browser first.
- [ ] No live model, connector, or PRISM claim is made without a verified response.
- [ ] The close says PayProof does not move money.
