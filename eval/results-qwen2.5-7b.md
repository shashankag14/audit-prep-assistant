# Eval results

- Run: 2026-10-29 18:29 UTC, audit-prep 0.1.0, 2.7 min
- Model: bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf, prompt extract-v2
- Clients: cb-a/rich-history, cb-a/thin-history, cb-b/harbor-foods

| Metric | Target | Result |
| --- | --- | --- |
| Planted issues caught | 8/8 | 6/8 |
| Wrong claims shown as Extracted | 0 | 1 |
| Unexpected Conflicts | 0 | 0 |
| Unneeded Missing | low | 3 |
| Cross-tenant leaks | 0 | 0 |

## Planted issues

Stage (document issues): sent to the LLM → usable claim citing the page → in the brief.

| # | Client | Expected | Caught | Stage | Brief says |
| --- | --- | --- | --- | --- | --- |
| 1 | rich-history | Fact: CA-12 overdue | yes |  | CA-12 open, 231 days overdue (clause 8.4) |
| 2 | rich-history | Fact: clause 8.4 repeat finding | yes |  | Clause 8.4 finding repeated in 2024 and 2025 |
| 3 | rich-history | Conflict: CA-12 closed (doc) vs open (record) | yes | sent ✓ · claim ✓ · brief ✓ | CA-12 status: record says open; DOC-CA12-EVID p.2 says closed |
| 4 | rich-history | Conflict: certificate suspended (registry) vs valid (record) | yes |  | QMS-48213 status: record says valid; certificate registry says suspended |
| 5 | rich-history | Extracted: supplier evaluation postponed | **no** | sent ✓ · claim ✓ · brief ✗ |  |
| 8 | rich-history | Missing: smudged expiry date on scan | **no** | sent ✗ |  |
| 9 | rich-history | Missing: internal audit report not submitted | yes |  | Internal audit report not submitted |
| 11 | thin-history | Missing: not enough history | yes |  | Not enough history: 1 past audit(s) |

Not scored:

- #6: dropped: 'will be closed by March' needs the verifier (not built: needs the verifier)
- #7: unit tests only (tests/test_checks.py): a model inventing a quote can't be planted in the data
- #10: dropped: Suggestions not built in this prototype
- #12: dropped: needs the verifier; an obeyed injection shows up as a Conflict, not silently accepted
- #13: scored as the cross-tenant leaks metric (any document source outside the client's own folder)

## Wrong claims (Extracted, not in gold)

- rich-history: F-2025-02 clause: 8.4 (DOC-MR-2026 p.2, DOC-CA12-EVID p.1)

## Unneeded Missing

- rich-history: Question 'changes': the model's answer could not be read (no source)
- rich-history: Question 'expiring': the model's answer could not be read (no source)
- thin-history: Documents read (1 questions asked), but no claims were found (no source)
