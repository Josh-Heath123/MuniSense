# Publication readiness (P1-17): 2026-11-18

This was a read-only check of what a public reader would see if the repository were made public. **The repository's visibility was not changed, and nothing in the history was changed.** The checks ran on every ref in the local clone, after `git fetch --all`.

## Secrets

- **gitleaks v8.30.1** (the image pinned in `.pre-commit-config.yaml`) scanned the full history (`--log-opts=--all`, redacted). It found **no leaks**.
- **Coverage:** it scanned 85 commits; git counts 91. The other 6 are 4 merge commits (their changes are in their parents) and 2 commits that add no text. So every commit that adds text was scanned.

## Personal data in file contents

Every added line in the history (PDFs, PNGs and `uv.lock` excluded) was searched by pattern. The table gives counts only; no value was copied out.

| Pattern | Hits | What they are |
| --- | --- | --- |
| 11-digit numbers (meter-number shape) | 69 | All are GitHub Actions run IDs in status and report links |
| 13-digit numbers (South African ID-number shape) | 0 | — |
| 20-digit numbers (prepaid token shape) | 0 | — |
| Bank names | 0 | — |
| Street addresses | 0 | — |
| Phone numbers | 0 | — |
| Email addresses | 0 real | All hits are Python decorators (`@pytest.mark…`) or `example.org` test values |
| Place names linked to the owner | 0 | No file links the owner to a place. The owner's meter location is not recorded (E34) |
| The owner's Linux username | 11 | In early P0 documents (environment checks, E1): a username and a home path |
| The owner's name | 16 files | As the owner and decider in CLAUDE.md, ADRs, status and reports, and as the copyright holder in `LICENSE` |

The owner's four prepaid purchase figures (dates, rand amounts and kWh, with no meter number, token or location) are committed in `data/observations/` (E39). They are listed in the POPIA register as "possibly personal information".

## Commit metadata

| Field | What a public reader would see |
| --- | --- |
| Author names | "Josh Heath" (62 commits), "Joshua Heath" (28, the merges made on GitHub) and "root" (1 early commit) |
| Author emails | About 87 commits carry email addresses that are not GitHub noreply addresses: the owner's private address, from before 2026-11-18. Since then, commits use the noreply address |
| Committer emails | 60 are not noreply; 28 are GitHub's own noreply address for merges made on the web |

Removing the private address or the names would need a history rewrite. That was not done, and CLAUDE.md treats it as irreversible, so it needs the owner's decision. The item is added to the security register's list for before publication.

## Third-party material

- The City of Ekurhuleni and SARS PDFs in `data/sources/` belong to their publishers. Whether they may be republished, or redistributed inside a proprietary repository, needs formal verification. The item is on the security register's list.
- The Bodoni Moda wordmark is OFL-licensed artwork (`docs/assets/FONTS.md`). The licence reading recorded there is not legal advice; it is on the same list.

## About box text (for the owner to set, W15)

**Description:** Exact, source-cited South African municipal electricity bill calculations. Every tariff value is cited to its page, and every rounding is named. Calculation core built; storage, API, staff console and MCP server planned.

**Topics:** `south-africa`, `electricity`, `electricity-tariffs`, `utility-billing`, `municipal`, `prepaid-electricity`, `decimal`, `provenance`, `python`, `pydantic`, `mcp`
