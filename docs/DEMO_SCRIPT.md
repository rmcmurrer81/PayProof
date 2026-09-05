# PayProof Atlas: 75-second judge demo

## Demo objective

Show one evidence-backed control conflict, one financially useful spending suggestion, and the workspace/source safety boundary. The story is: **less time chasing records, more confidence before a human acts.**

## Preflight checklist

- [ ] Run `Start PayProof.cmd` and wait for the browser to open after the health check.
- [ ] Use the bundled synthetic data; a live bank or Gmail account is not required.
- [ ] Start in the **Meridian Works** workspace with the Atlas view visible and drawers closed.
- [ ] Confirm the **Backup operations** control is visible in the left rail.
- [ ] Confirm **Personal Example** is available in the workspace picker.
- [ ] If PRISM or the runtime model is not configured, leave the truthful **NEEDS KEY** or **LOCAL FALLBACK** label visible.
- [ ] Do not open a live connector during the timed pitch unless its sandbox/test setup was verified immediately beforehand.
- [ ] Start the timer only after the dashboard is fully loaded.

## Timed script

| Time | On screen | Say |
|---|---|---|
| 0-8 sec | Meridian Works evidence atlas | "Small finance teams investigate across bank portals, inboxes, receipts, and intake folders. PayProof brings those records into one evidence map so they can see what changed before money moves." |
| 8-23 sec | Click **Are backups current?**, then point to **Backup operations** | "Here, policy says backups must run daily, but the operating evidence shows failed jobs. PayProof calls that a conflict, cites the record, and asks for the missing owner or restore evidence instead of inventing compliance." |
| 23-34 sec | Point to the evidence IDs and open **Context used** | "The math and control result are deterministic. A model can only reword this bounded packet; it cannot change the numbers, sources, uncertainty, or approval state." |
| 34-51 sec | Switch to **Personal Example** and ask **Where could I cut spending?** | "The same engine spots a sudden increase against the prior monthly baseline and suggests a possible cut. Crucially, Amazon alone does not prove food or drinks; PayProof only names a category when email, receipt, or intake evidence itemizes it." |
| 51-66 sec | Open **Sources & settings** | "Every bank connection, Gmail authorization, local statement, and intake folder is assigned to the active company workspace. Imports are previewed, reconciliation links are suggestions, and corrections preserve their full history." |
| 66-75 sec | Leave Sources open or return to the atlas | "Our Golden Rule is simple: evidence may inform a decision, but it never authorizes one. PayProof does not move money; it gives the human a defensible next step and an audit trail." |

## Presenter cues

- Keep the cursor near the element being discussed; do not tour every control.
- Let the assistant finish before speaking about its evidence IDs.
- Say **conflict**, **anomaly**, or **suggestion**. Do not say **fraud**, **approved**, or **compliant** unless the displayed evidence supports it.
- Call the provider status **Mocked** when showing automated Plaid or Gmail tests. Use **Live** only after a successful real provider response.
- If the model badge says **LOCAL FALLBACK**, frame it as a feature: the deterministic workflow remains usable without a model endpoint.
- If the PRISM badge says **NEEDS KEY**, say that live trace delivery requires the submission credentials; do not imply a trace was accepted.

## Ten-second optional company-workspace extension

Use this only if the total recording can reach 85 seconds and the current build was preflighted:

1. Open the workspace controls and show a custom company.
2. Open **Sources & settings** for that company.
3. Say: "Source assignment follows the selected company, so identical upstream IDs cannot overwrite another workspace's records."

Do not create a new company or browse for an intake folder live unless that exact flow was rehearsed on the recording machine.

## Recovery lines

- **Provider not configured:** "The connector is intentionally disabled until server credentials and protected token storage are present; local statement import still works."
- **Model unavailable:** "PayProof keeps the deterministic answer and labels the fallback instead of hiding the failure."
- **PRISM delivery unavailable:** "The UI does not claim acceptance; a configured failed delivery is queued locally for retry."
- **Short on time:** Skip **Context used** and move directly from the backup conflict to the spending suggestion.

## Final recording checklist

- [ ] Duration is between 60 and 90 seconds.
- [ ] Default data is identified as synthetic.
- [ ] At least one cited evidence conflict is visible.
- [ ] The spending suggestion includes a baseline and uncertainty.
- [ ] Multi-company source assignment is stated without exposing credentials.
- [ ] No connector is called Live unless it actually succeeded.
- [ ] The close explicitly says PayProof does not move money.
