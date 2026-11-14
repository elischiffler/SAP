# Grouped notifications

Alloy is the default hosted voice. One group produces one bounded WAV and uses the same one-at-a-time claim, heartbeat, and acknowledgment protocol as a solo notification.

## Matching and batching

The group key is normalized application plus, in order: explicit conversation ID, explicit sender ID, or nonblank sender label. These namespaces stay separate. Explicit conversation IDs allow multiple senders in the same group chat; using separate IDs keeps a solo conversation separate from a group involving that contact. Labels alone cannot distinguish contacts with identical names, so a real bridge should supply stable identifiers when available. With no identity metadata, notifications stay separate rather than combining unknown people. ANCS does not universally provide conversation IDs or sender metadata, so hardware grouping depends on what the bridge can actually obtain.

After the first classification reservation, the worker waits up to 0.5 seconds and collects up to ten matching pending inputs. One GPT call returns a priority and short factual digest for every visible member. The complete received body, up to 4,096 characters, is considered; do not trim it to the audio preview before classification. Output index validation rejects missing, duplicate, or mismatched results. Hidden previews use the generic local fallback. Batch failure leaves every member explicitly failed for retry; partial model results are not applied.

Priority 1–2 contents are deleted and excluded from the group count. Retained members join an unclaimed group within sixty seconds of its first server arrival, up to fifty members. A two-second quiet delay reduces repeated audio generation. Matching raw notifications still being classified defer ordinary group summarization within the admission window. Priority 5 bypasses that delay and materializes first; this can intentionally require extra speech/summary work if more messages arrive afterward.

## Speech and fidelity

Solo playback keeps the strict source preview format. Group playback is a paraphrase, without quotation marks, beginning with the count:

> 3 notifications on iMessage from Dinner plans: Sam asks you to confirm dinner at 7 and use the Pine Street entrance.

The final model sees chronological factual per-message digests, including sender, priority, and receipt time. These preserve relevant details from the full classifier input, including details beyond the solo preview's 350-character limit. The final digest has at most 200 characters; the app supplies and validates the count and source prefix. The instructions prioritize actions, changed plans, deadlines, danger, uncertainty, and negation, and direct listeners to the phone if more actionable details will not fit.

Compression and classification can make mistakes. This is a brief, not a complete transcript, and important-information recall has not been established by a large evaluation. Context is shared within each ten-message classification batch; earlier batches are not a persistent conversation memory. Corrections can therefore still be misinterpreted across batch boundaries. Generated summaries must not be advertised as emergency-reliable.

## Frozen playback and persistence

The group's priority is the maximum of its retained members; a summary cannot lower it. Delivery order is priority descending (5, 4, 3), then notification source timestamp ascending within each priority, with server arrival breaking ties. Groups keep the source timestamp of their first-arriving member, including when new members raise the group’s priority. The highest-ranked classified item holds its position while preparing audio; unclassified items have no tier yet, and failed items are skipped until retried. Phone timestamps also order details inside the digest. A delayed standalone notification can sort before a newer notification in the same priority tier; a later member cannot move an existing group. Admission windows and batch collection still use the server arrival clock. Claims permanently seal membership, including after Stop, lease expiry, or manual retry. Later arrivals create another group. Playback never downloads or speaks a second group automatically.

New arrivals can replace ready, unclaimed audio only after reserving enough provider budget for its new summary and speech. The old audio becomes unclaimable transactionally before removal. If budget is insufficient, the already playable group stays intact and the new message remains separate. A played ACK deletes all member contents and creates opaque deduplication records for each original event ID. Retry/restart never loses group membership.

## Usage and capacity

A simulated fifty-message burst produced five classification batches, one summary, and one speech operation: seven operations total. That is a tested best-case burst, not a fixed cost for all conversations. Slow arrivals, different contacts, urgent interruptions, group limits, playback during arrivals, or retries can produce additional calls. Provider billing depends on input/output tokens and generated speech, not just request count. The summaries add model output tokens but save repeated prompts and repeated audio generation.

The durable provider counter counts adapter operations, including a batch as one operation and including local demo operations. Input capacity counts original notifications, even after grouping. Defaults: one worker, 100 outstanding notifications, 50 per group, 10 per classification call, 45 seconds/5 MB per WAV, five delivery attempts. Beyond a group's size/window limit, another group is created; no message is silently dropped to make a summary fit. Ingress beyond the queue limit is rejected with HTTP 429 for the sender to handle.

Completed-event IDs and delivery receipts each retain the newest 10,000 entries. Retrying an event older than that window can treat it as new. Played/discarded aggregate counts remain durable after history pruning.
