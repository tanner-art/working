# Suggested grouping review foundation

This slice adds a review-only foundation for suggesting related captures. It does not add a
visible review panel or call an external AI provider.

`groupingSuggestions.ts` compares preserved capture content, context, and capture-time
proximity. Its deterministic baseline returns proposals in `review` state. Existing
`relates_to` capture pairs are removed before a proposal is returned. A provider seam and
runtime validator are present for later integration; provider payloads cannot choose review
state, create links, or reference captures outside the supplied input.

`groupingProposal.ts` owns the review decision boundary. Persisting or cancelling a proposal
creates no link. A dedicated confirmation accepts explicit candidate IDs and creates only
that selected subset. Rejection creates no link. Reversal removes only the active links made
by the named confirmation. Proposals and append-only decision history retain capture IDs,
observed rule signals or explicit provider attribution, generator details, timestamps, selected candidates, suppressed duplicates,
and created/removed relationship IDs.

The schema-v2 model accepts an optional `groupingReview` record. Old records remain valid.
When the field is present, load validation checks capture references, review states,
provenance, decision references, unique IDs, and active-pair uniqueness before exposing data.
The existing local and account serializers carry the additive record without special cases.

## Integration steps

1. Generate suggestions from `PersistedState.captures` and pass the currently active capture
   links to `suggestGroupingProposals`.
2. Add each result with `persistGroupingProposal`, then save through the existing state
   serialization path.
3. Render only proposals whose `reviewState` is `review`. The confirmation control must pass
   the exact candidate IDs selected by the user to `confirmGroupingProposal`.
4. Save the returned state. Reject and reverse through their dedicated operations; do not
   update proposal state or relationship arrays directly.
5. If a hosted provider is added, keep credentials server-side and run every response through
   `validateProviderGroupingProposal` before persistence.

Grouping relationships currently connect immutable capture identities and remain separate
from legacy object-derived semantic relationships. A future UI can display them as related
thoughts without filing, merging, moving, or rewriting source captures.
