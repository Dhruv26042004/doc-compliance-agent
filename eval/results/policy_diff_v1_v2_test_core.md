# Policy v1 → v2 on `test_core`

2331 clauses in 30 documents. Same pipeline (`v1+pf+fs+ver`) and model (`gemini-3.5-flash-lite`).

## What changed in the policy

- R-05 narrowed: only automatic (evergreen) renewals and their non-renewal notice periods are flagged. Renewal options that need both parties to agree are no longer flagged; legal found them low-risk and noisy.
- R-09 changed from prohibited to review: the business now accepts IP assignment in services and development deals, subject to legal review. What matches is unchanged; the verdict becomes a flag instead of a violation.

| Rule | Fields changed |
|---|---|
| R-05 Automatic renewal | title, definition, matches, does_not_match, edge_notes |
| R-09 Transfer of IP ownership | kind, severity, definition |

## Clause-level shift

| Rule | Changed in policy? | Matched v1 | Matched v2 | Gained | Lost |
|---|---|--:|--:|--:|--:|
| R-01 Limitation of liability required | no | 24 | 25 | 3 | 2 |
| R-02 Uncapped liability prohibited | no | 4 | 6 | 2 | 0 |
| R-03 Governing law required | no | 25 | 27 | 2 | 0 |
| R-04 Termination for convenience | no | 5 | 3 | 0 | 2 |
| R-05 Automatic renewal | **yes** | 11 | 6 | 1 | 6 |
| R-06 Non-compete and non-solicitation of customers | no | 14 | 12 | 0 | 2 |
| R-07 Exclusivity | no | 23 | 17 | 2 | 8 |
| R-08 Assignment and change-of-control restrictions | no | 31 | 31 | 4 | 4 |
| R-09 Transfer of IP ownership | **yes** | 7 | 10 | 3 | 0 |
| R-10 Most favored nation pricing | no | 1 | 1 | 0 | 0 |
| R-11 Liquidated damages and penalties | no | 3 | 2 | 1 | 2 |
| R-12 Audit rights | no | 16 | 17 | 2 | 1 |

**Noise floor:** rules the policy did not change still flipped on 37 clauses (against 146 matches in v1). Shifts in changed rules should be read against that.

## Document outcomes

| Rule | Outcome change | Documents |
|---|---|--:|
| R-01 Limitation of liability required | violated → satisfied | 2 |
| R-01 Limitation of liability required | satisfied → violated | 1 |
| R-02 Uncapped liability prohibited | clear → violation | 2 |
| R-03 Governing law required | violated → satisfied | 2 |
| R-04 Termination for convenience | flag → clear | 2 |
| R-05 Automatic renewal | flag → clear | 5 |
| R-06 Non-compete and non-solicitation of customers | violation → clear | 1 |
| R-08 Assignment and change-of-control restrictions | flag → clear | 1 |
| R-09 Transfer of IP ownership | violation → flag | 6 |
| R-09 Transfer of IP ownership | clear → flag | 2 |
| R-11 Liquidated damages and penalties | flag → clear | 2 |
| R-11 Liquidated damages and penalties | clear → flag | 1 |
| R-12 Audit rights | clear → flag | 1 |

## Examples of changed decisions

**R-05 Automatic renewal**

- `C0012-S0129` no longer matches: “13.1 This Agreement shall remain in effect for sixty (60) months from the Effective Date (the "Initial Term"). After the Initial Term, the term of the Agreement may be extended by a further period of five (5) years by mutual written agreement by the parties in the form of an amen…”
- `C0194-S0014` now matches: “K. SCIEN will provide HEMISPHERX with copies of Product specification sheets, Product inserts, user manuals, user bulletins, and user Product updates and any other customer materials such as brochures, educational materials, web pages or other electronic information relating to S…”
- `C0293-S0016` no longer matches: “11. The Term of this Agreement will commence on the date above, and shall continue for a term of one (1) year. mPhase shall have the right to annually renew this agreement for a period of one year upon each annual expiration with the written consent of Lucent, which written conse…”

**R-09 Transfer of IP ownership**

- `C0174-S0006` now matches: “1.5 Transferred Patent(s) The term "Transferred Patent" or "Transferred Patents" means the patents and/or patent applications listed in Exhibit A to this IP Agreement and all patents and applications claiming the priority of any of these patents and/or patent applications and all…”
- `C0190-S0052` now matches: “8.1 All right, title and interest in and to TDA's Golf Instruction Related Products shall be and remain the absolute property of TDA forever (it being understood that after the Term TDA may continue to manufacture, promote, sell and/or distribute its other golf instruction relate…”
- `C0214-S0027` now matches: “3.3 Neither Party shall make a trade secret of the other Party public or otherwise destroy or impair the trade secret status of such trade secret without the express, advance, written consent of the other Party. Any agreement by which a trade secret is transferred or sublicensed …”

## Against the CUAD reference labels

CUAD labels follow the v1 definitions, so a narrowed rule is expected to lose recall against them.

| Rule | v1 precision / recall | v2 precision / recall |
|---|--:|--:|
| R-05 | 64% / 100% | 83% / 71% |
| R-09 | 71% / 28% | 60% / 33% |
