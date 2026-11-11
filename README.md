# Last Price · evidence kept off the plugin branch

Two duel transcripts from the 0.1.2 bench (`docs/RESULTS.md` on `main`). They are kept here, not on `main`,
because Hermes's install-time plugin scanner reads text quoted inside them as instructions to an agent and
marks the plugin "caution", which blocks a plain `hermes plugins install`. The files are unchanged.

* `haiku-4.5/4128d2a1e3fc.json`: the `authority` duel in which Claude Haiku 4.5, as the buyer, declined to
  impersonate the owner's manager (its refusal lists the tactics it was asked to use).
* `hermes-4-70b-seller/08d644f06cf8.json`: the one duel with `nousresearch/hermes-4-70b` as the seller; both
  arms got Hermes's error text (OpenRouter: no provider serves the model; the text links to OpenRouter's model
  list).
