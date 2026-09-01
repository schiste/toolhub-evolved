# Critical-path mutation testing

The weekly `Python mutation` workflow mutates authentication, outbound-I/O,
and data-integrity modules. It reports one score per area so a gain in a large
module cannot hide a regression in a smaller security boundary.

The committed ratchet in `.python-mutation-ratchet.json` is monotonic. Lowering
a floor requires a reviewed explanation; new killed mutants should raise the
corresponding floor after a clean Linux run.

## Survivor triage

Classify each survivor before changing production code:

1. **Missing behavioral assertion** — add a focused test for the externally
   relevant decision or boundary. The current critical-path suite covers auth
   precedence and caching, cryptographic error contracts, normalization limits,
   DNS destination selection, and response-size boundaries.
2. **Equivalent mutant** — record it during review and leave it out of score
   claims. Typical examples are spelling-only encoding changes and replacing an
   explicit default with the same implicit default.
3. **Broad orchestration mutant** — add a narrow seam or invariant test before
   asserting implementation details. These remain concentrated in write,
   inference, and source-analysis orchestration.
4. **Infrastructure result** — `suspicious`, interrupted, and segfault results
   fail the workflow and do not count toward an area score. Timeouts count as
   caught, matching Mutmut's CI statistics.

The canonical measurement is the scheduled Ubuntu run with two workers. Local
macOS runs can produce false `suspicious` results when a Python child process
initializes system proxy state after `fork`; do not use such a run to move a
ratchet.

## Current direction

The focused survivor tests raised the locally measured authentication score
from 72.90% to 87.85% and outbound-I/O from 65.00% to 68.16%. Data-integrity
remains the largest opportunity: prioritize write validation, inference
enrichment, and source-analysis decisions, with 100% as the target rather than
treating the current floor as an acceptable endpoint.
