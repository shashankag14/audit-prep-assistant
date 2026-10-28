# Synthetic data

All data is made up. Two tenants (certification bodies), three clients.

```text
data/
  scheme_profiles/iso9001.json        clauses, term map, claim fields, questions per audit type
  tenants/
    cb-a/clients/rich-history/        3 audits, repeat findings, open CAs
    cb-a/clients/thin-history/        1 past audit, no findings
    cb-b/clients/harbor-foods/        other tenant, used for the leak test
```


## Planted issues in the records

Numbers match the planted-issue table in the prototype plan.

| # | Where | What | Expected |
| --- | --- | --- | --- |
| 1 | rich-history, CA-12 | open, due 2026-03-31, audit 2026-11-17 | Fact: overdue |
| 2 | rich-history, F-2024-03 + F-2025-02 | clause 8.4 in two audits in a row | Fact: repeat finding |
| 9 | rich-history, submitted_documents | no internal audit report (expected by the profile) | Missing: absent |
| 11 | thin-history | one past audit, no findings | Missing: not enough history |
| 13 | cb-b, harbor-foods | also has a CA-12 (closed) and an 8.4 supplier finding | never shows up for CB-A (for data leakage) |
| - | rich-history, CA-13 | empty due date | Data quality gap, not "on time" |
| - | rich-history, AUD-2026-S2 scope | 7.1.5 and 8.7 not sampled in the last 2 audits | Not sampled section |

Dates are judged against the planned audit date, not today, so results don't change over time.
