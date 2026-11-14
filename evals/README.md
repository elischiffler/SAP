# Classifier evaluation cases

`classification.json` contains synthetic notifications separate from the prompt examples and the five scripted demos. Submit each `notification` object through the local app in OpenAI classifier mode. Run the hidden-preview case through the API to set `content_hidden`. The `expected_priority`, optional `expected_evidence`, and `check` fields are evaluation labels and stay out of the API request.

Review actual versus expected priority, routing across the 2-to-3 boundary, missed or incorrect level-5 alerts, and fidelity of each available spoken summary. Check the discard counter for priorities 1–2 because their details are deleted immediately. To measure exact priority for discards, call the classifier directly using only these synthetic cases. Record latency separately from accuracy and list the configured classifier model with any results.
