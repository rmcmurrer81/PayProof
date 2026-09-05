# Synthetic intake paperwork

This folder is generated from the machine-readable examples in
`data/demo_intake/`. Every PDF is fictional and prominently marked
`SYNTHETIC DEMO - NOT A REAL BILL OR RECEIPT`.

The set deliberately mixes routine paperwork with review scenarios such as a
missing receipt, a possible duplicate, a high-value gift-card purchase, and an
unapproved annual software commitment. These are warning patterns for a human
to investigate, never conclusions that fraud occurred.

Rebuild the PDFs with:

```powershell
python tools/build_demo_paperwork.py
```
