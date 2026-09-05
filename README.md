# PayProof Atlas

**Detect what changed before money moves.**

PayProof Atlas is a visual financial trust-and-risk assistant built for the AI × FINANCE — MONEY TALKS hackathon. It turns approved financial records into an interactive 3D relationship map, explains period changes, identifies evidence-backed anomalies and adversarial instructions, and keeps consequential decisions under human control.

PayProof targets the **Trust & Risk** track: safer financial decisions through evidence collection, control monitoring, human approval, auditable AI context, and defensible risk explanations. It is still a useful small-business bookkeeper, but bookkeeping records become the evidence layer for trust decisions rather than an excuse to let an agent act autonomously.

## Judge quick start

1. Double-click `Start PayProof.cmd`.
2. The browser opens to a complete synthetic example. No account or setup is required.
3. Select **Guided demo**, click graph nodes, or ask **What changed?**
4. Switch to **Change** to see period movement and select a finding.
5. Open **Sources** to add or remove Gmail/CSV evidence.

The primary example is fictional. It shows a $48,750 invoice proposing destination `****9142` where the previously verified destination was `****7284`. PayProof describes this as an anomaly requiring verification, not proof of fraud.

## Windows setup

The easiest path is `Setup PayProof.cmd`. Manual PowerShell setup:

```powershell
cd C:\path\to\payproof
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:8765>.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Ask PayProof runtime AI

Ask PayProof always calculates totals and findings with deterministic Python code. With no model configuration it clearly displays **LOCAL FALLBACK** and remains fully usable. To enable a live OpenAI-compatible Chat Completions endpoint, set these values in `.env`:

```text
PAYPROOF_MODEL_BASE_URL=http://127.0.0.1:your-port/v1
PAYPROOF_MODEL_API_KEY=your-runtime-key
PAYPROOF_MODEL=your-model-name
```

The model receives a bounded packet containing the question, deterministic answer, evidence IDs, and calculation. If the model times out or returns invalid data, PayProof preserves the deterministic answer and reports fallback mode. GIDE's development model is separate and is not automatically inherited by PayProof.

Useful chat checks include “What changed?”, “Show money in and money out,” “Which employee expense reports need review?”, “Find duplicates,” and “How much did I spend at Amazon?” in the Personal Example workspace.

## Sources and privacy

The built-in example and uploaded records use the same parser, local database, calculations, graph, and chat. Synthetic emails are visibly labeled. Gmail requests read-only access and stores only message metadata and short snippets locally; it does not store attachments or full bodies. Imported sources can be removed from the Sources drawer.

PayProof also watches a local `intake` folder for structured JSON bookkeeping paperwork. Open **Sources → Scan intake folder** after adding a file. The included synthetic employee reports in `data/demo_intake` use the same idempotent parser and appear as clickable employee/report nodes in the atlas. They are fictional and safe for demonstrations.

For Gmail, place a Google Desktop OAuth client file named `credentials.json.json` in the project directory. Open **Sources → Connect Gmail**, approve read-only access, then import selected message evidence. The credentials and local token files are excluded by `.gitignore`.

## PRISM

Create `.env` from `.env.example` and provide:

```text
PRISMTRACE_HOST=https://prism.blockconvey.com
PRISMTRACE_PROJECT_ID=your-project-uuid
PRISMTRACE_API_KEY=your-ingest-key
```

PayProof sends server-side traces with `X-PRISMtrace-Key`, stable session/trace identifiers, latency, and evidence metadata. The dashboard distinguishes not configured, accepted, queued, and failed states. A failed delivery is queued locally and never shown as accepted.

## Safety boundaries

PayProof does not move money, contact vendors, or connect to banks. Review buttons record simulated local actions. Deterministic code performs financial calculations and field comparisons. Chat answers cite loaded evidence and disclose when it cannot answer.

## Repository hygiene

Never commit `.env`, OAuth credentials, Gmail tokens, imported financial data, local databases, or trace queues. Distributed company and personal identity fields remain blank.
