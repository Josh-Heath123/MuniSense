---
name: add-tariff
description: Add or update a supplier's tariffs end to end, from source document to published, verified data with golden bills.
argument-hint: "<supplier> <tariff year, e.g. 2026/27>"
disable-model-invocation: true
---

# /add-tariff

This is the target workflow. The tooling for steps 3, 4 (the deterministic citation check) and 6 is built in P2 and proven end to end in P3. Before then, do as much as the existing code allows and say which steps are not yet possible. Complete each step before starting the next.

1. **Source.** Find the official document for `$ARGUMENTS`: the municipal tariff schedule or budget annexure, or the Eskom tariff book or rate card. Download only from the supplier's official website, and ask the owner before downloading (the owner has already approved the Ekurhuleni 2026/27 electricity schedule for P1). Record the URL, retrieval date, SHA-256, title, council resolution or approval reference and effective dates. Keep the file under `data/sources/` and commit it (ADR-0006).
2. **Draft.** Transcribe each tariff into the structured draft format. Every value carries:
   - the original text exactly as printed
   - the canonical value and unit
   - page and table or row reference
   - customer class, meter type, phase and season
   Never silently normalise an ambiguous number such as "R3.77,05". Flag it for the owner.
3. **Validate.** Run the ingestion validator and fix every schema error.
4. **Verify.** Run the `tariff-verifier` subagent, then the deterministic citation check. Under ADR-0006 a value is `verified` only when (a) its original printed text is found verbatim in the extracted text of the cited page, and (b) the verifier's identity, method and date are recorded. A subagent match alone is not enough. A scanned page without a text layer needs a human check. Until the deterministic check exists (P2), values stay `estimated`, with that as the reason. The first tariff of each supplier also needs the owner's check.
5. **Golden bills.** Add at least one golden bill per tariff, from a real bill anonymised to figures only, or from an official worked example. A prepaid golden case is a whole month of purchases, not a single receipt. If neither exists, mark the tariff unverified and say so.
6. **Publish.** Publish only through the review-and-publish workflow. Publishing writes the reviewed tariff file with its record time stated explicitly (never taken from git history); the file reaches `main` through a pull request (ADR-0003). The first tariff of each supplier needs the owner's confirmation.
7. **Report.** State what was loaded, what remains `estimated`, any discrepancies, and anything the source document left ambiguous.
