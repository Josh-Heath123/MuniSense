---
name: add-tariff
description: Add or update a supplier's tariffs end to end, from source document to published, verified data with golden bills.
argument-hint: "<supplier> <tariff year, e.g. 2026/27>"
disable-model-invocation: true
---

# /add-tariff

This is the target workflow. The tooling for steps 3 and 6 is built in phases 3 and 4. Before then, do as much as the existing code allows and say which steps are not yet possible. Complete each step before starting the next.

1. **Source.** Find the official document for `$ARGUMENTS`: the municipal tariff schedule or budget annexure, or the Eskom tariff book or rate card. Ask the owner before downloading. Record the URL, retrieval date, SHA-256, title, council resolution or approval reference and effective dates. Keep the file under `data/sources/`, which is git-ignored.
2. **Draft.** Transcribe each tariff into the structured draft format. Every value carries:
   - the original text exactly as printed
   - the canonical value and unit
   - page and table or row reference
   - customer class, meter type, phase and season
   Never silently normalise an ambiguous number such as "R3.77,05". Flag it for the owner.
3. **Validate.** Run the ingestion validator and fix every schema error.
4. **Verify.** Run the `tariff-verifier` subagent. A value is `verified` only when the verifier matched it to the page. Otherwise it is `estimated`, with a reason.
5. **Golden bills.** Add at least one golden bill per tariff, from a real bill anonymised to figures only, or from an official worked example. If neither exists, mark the tariff unverified and say so.
6. **Publish.** Publish only through the review-and-publish workflow. The first tariff of each supplier needs the owner's confirmation.
7. **Report.** State what was loaded, what remains `estimated`, any discrepancies, and anything the source document left ambiguous.
