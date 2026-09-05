# PayProof Atlas demonstration

## 30-second pitch

PayProof Atlas gives finance teams a visual explanation of what changed and the evidence behind it. It connects invoices, transactions, receipts, vendors, locations, and approved email evidence in an interactive map. Deterministic controls catch consequential changes, while AI receives only the relevant context needed to explain them. PRISM records the interaction, and a human remains responsible for every payment decision.

## Two-minute judge flow

1. Open PayProof to the preloaded synthetic Meridian Works workspace.
2. Select **Guided demo**. Point out the green verified route and animated red proposed route.
3. Ask **What changed?** PayProof identifies `****7284 → ****9142`, cites evidence, and avoids claiming fraud.
4. Select **Change** to show spending across periods and all findings.
5. Open **Evidence**, then record a simulated **Hold** or **Review** action.
6. Open **Sources** to show Gmail, CSV preview, and removable imported sources.
7. Show the PRISM trace status and the bounded **Context used** drawer.

Close with: “PayProof explains financial change from the records that matter, proves what the AI saw, and keeps humans in control before money moves.”

## Likely judge questions

**What did you use?**  
GIDE was the mandatory development environment. PayProof uses Python, Flask, SQLite, a custom browser visualization, Google Gmail read-only OAuth, and Block Convey PRISM tracing.

**Why use AI?**  
People ask questions in many ways and need a clear explanation. Deterministic code calculates totals and detects changes; the model interprets the request and explains a bounded evidence packet.

**Can it work for different companies?**  
Yes. The example and imported records use the same data path. A company can upload the template or connect approved sources without editing code.

**Is the invoice fraudulent?**  
PayProof does not make that claim. It identifies a payment destination change and recommends independent verification using previously verified contact information.

**What happens without the internet?**  
The visual map, data import, calculations, findings, chat fallback, and review actions continue locally. PRISM traces queue locally and the interface reports that they were not accepted yet.

**Does it move money?**  
No. Every displayed action is simulated and stored only in PayProof’s local audit history.

