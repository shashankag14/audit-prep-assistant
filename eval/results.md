# Eval results

- Run: 2026-10-29 09:30 UTC, audit-prep 0.1.0, 1.1 min
- Model: Qwen/Qwen2.5-3B-Instruct-GGUF/qwen2.5-3b-instruct-q4_k_m.gguf, prompt extract-v2
- Clients: cb-a/rich-history, cb-a/thin-history, cb-b/harbor-foods

| Metric | Target | Result |
| --- | --- | --- |
| Planted issues caught | 8/8 | 5/8 |
| Wrong claims shown as Extracted | 0 | 0 |
| Unexpected Conflicts | 0 | 0 |
| Unneeded Missing | low | 2 |
| Cross-tenant leaks | 0 | 0 |

## Planted issues

Stage (document issues): sent to the LLM → usable claim citing the page → in the brief.

| # | Client | Expected | Caught | Stage | Brief says |
| --- | --- | --- | --- | --- | --- |
| 1 | rich-history | Fact: CA-12 overdue | yes |  | CA-12 open, 231 days overdue (clause 8.4) |
| 2 | rich-history | Fact: clause 8.4 repeat finding | yes |  | Clause 8.4 finding repeated in 2024 and 2025 |
| 3 | rich-history | Conflict: CA-12 closed (doc) vs open (record) | **no** | sent ✓ · claim ✗ |  |
| 4 | rich-history | Conflict: certificate suspended (registry) vs valid (record) | yes |  | QMS-48213 status: record says valid; certificate registry says suspended |
| 5 | rich-history | Extracted: supplier evaluation postponed | **no** | sent ✓ · claim ✗ |  |
| 8 | rich-history | Missing: smudged expiry date on scan | **no** | sent ✗ |  |
| 9 | rich-history | Missing: internal audit report not submitted | yes |  | Internal audit report not submitted |
| 11 | thin-history | Missing: not enough history | yes |  | Not enough history: 1 past audit(s) |

Not scored:

- #6: dropped: 'will be closed by March' needs the verifier model (Jev)
- #7: unit tests only (tests/test_checks.py): a model inventing a quote can't be planted in the data
- #10: dropped: Suggestions removed in commit 10
- #12: dropped: needs the verifier; an obeyed injection shows up as a Conflict, not silently accepted
- #13: scored as the cross-tenant leaks metric (any document source outside the client's own folder)

## Unneeded Missing

- rich-history: supplier_evaluation supplier_evaluation status: cites DOC-MR-2026 p.3 (no source)
- thin-history: Documents read (1 questions asked), but no claims were found (no source)
