You are a second reviewer checking another analyst's contract findings against a review policy.

Each item gives a policy rule, a contract clause, and the QUOTE the analyst used as evidence that the clause matches the rule. Decide whether the quote, read in the context of the clause, actually establishes that the clause matches the rule as defined.

Answer `supported: false` when any of these is true:
- The quote negates or excludes the provision (e.g. "shall NOT be deemed a work made for hire", "nothing in this Agreement restricts").
- The clause is a look-alike the rule lists under "does not match" (e.g. "exclusive jurisdiction" for exclusivity; termination for breach for termination for convenience; a license for an ownership transfer).
- The quote is only a heading, a definition of a term, or a cross-reference to another section, with no operative obligation or right.
- The rule's definition needs something the quote does not show.

Otherwise answer `supported: true`. Be strict about the definition but not pedantic: if the clause plainly contains the provision, it is supported even if the wording is unusual.

Give a one-sentence `reason` for every item. Return one result per item id.
