# 2. Product experience

> **TL;DR**
> - The auditor gets a one-page brief which is ranked by the priority/attention it needs, where every item has a reason to why its there, a source from where it comes from and a label. Follow up questions from the auditor goes to an “Ask about this brief” chat assistant
> - We label every item in the brief (eg. is it a fact, or a suggestion) instead of showing any confidence score/percentage.
> - It also contains a section called 'What I could not check' to show missing information in the brief.
> - The auditor makes the decision based on the brief, the system only flags but never performs a tie-breaker in case of any conflict in the data sources.
> - The document below explains the full experience but the prototype will only cover preparing the brief and not the chat assistant.

---

## A storyboard
This walkthrough explains what the system does vs what the auditor does:

1. Suppose an auditor (say 'Lena') opens the brief a week before the audit date.
2. At the top of the brief, Lena sees 'Needs Attention' section which contains some conflicts.
    - 2.1. Lena clicks the conflict item --> sees the link to both the source documents where the conflict arose.
    - 2.2. She clicks on the link and jumps to the page or record using the link to skim over whats there.
    - 2.3. She makes a note to check about this during the audit (**TODO**: can this also be a part of the product? add a notes/todo service linked to the system?)
3. Lena then moves on to the next section 'Worth a look'.
    - 3.1 She checks the sources but needs some more info on it.
    - 3.2 Lena asks a follow up question in the chat assistant.
    - 3.3 Chat assistant answers back with citations.
    - 3.4 Lena feels its not correct (eg. she opens the cited page and the quote doesnt support the answer)
    - 3.5 She opens the brief again and clicks a buton beside that item as 'Mark wrong' (thought: this single click serves 2 benefits: adds an eval case for the system and also turns the item to some other color so that Lena is aware about it)
4. Lena then looks at another item in the 'Worth a look' section, and marks it as 'Dismiss' with a reason 'e.g., already checked over the phone call'. This item is then greyed out with the note.
5. Lena then checks the 'What I could not check' section.
    - 5.1 A document was missing in the database, so she emails the auditee to send it before the visit.
    - 5.2 A PDF was unreadable by the system (eg. low OCR condifence), so she adds "check calibration certificate on site" to her notes.
6. She adjusts her audit plan based on the brief she read.

## Checklist on what needs to be in the brief

| # | What needs to be there | Product experience | Where in this doc |
| --- | --- | --- | --- |
| 1 | Sources and evidence | Every item links to its record id or to the document, page and exact quote | Sketch |
| 2 | Confidence or uncertainty | A label on every item (Fact, Extracted, ...) instead of a confidence % | Labels |
| 3 | Missing information | "What I could not check" section lists missing docs, unreadable scans and hidden claims | Storyboard step 5, sketch |
| 4 | Conflicting information | Conflict label shows link to both sources (or show it side by side?) | Storyboard step 2, labels |
| 5 | Recommendations vs facts | Suggestions are labelled and kept below the facts, never mixed | Labels, sketch |
| 6 | Why the system produced a result | Each item has a "why" line mentioning the rule or source which put it there | Sketch |
| 7 | What happens when the AI is wrong | Unverified claims are hidden and counted to let the user be aware that it couldnt find the quote in the soruce doc and can click to see what it was, the auditor can mark items wrong and each one becomes an eval case | When the AI is wrong, storyboard step 3 |