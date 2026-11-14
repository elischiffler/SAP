# Implementation handoff and demo plan

Implementation is underway. Root owns shared contracts, dependencies, startup scripts, documentation, and integration. The server and intelligence workers use GPT-6.1 Sol with high reasoning; the Mac interface worker uses GPT-6.1 Sol with medium reasoning. A separate user-owned chat builds the product showcase; do not dispatch a duplicate showcase agent.

Current scope is Mac notification TTS only. Hardware work belongs to the user's teammate for now; do not dispatch component connection, flashing, Bluetooth pairing, GPIO, or Pi audio tasks. EC2 deployment and showcase assets follow the working local playback milestone.

## Current ownership

The implementation contract is `docs/LOCAL_CONTRACT.md`; it supersedes the earlier proposed endpoint list in PLAN.md. Shared Pydantic models and configuration live in `contracts/`. Agents propose contract changes to root before consumers diverge. Keep implementation in independently owned directories.

| Owner | Scope and files | Done when |
| --- | --- | --- |
| Root: integration | `contracts/`, `scripts/`, root dependency/configuration files, documentation, contract tests | Components agree on validated contracts; setup is reproducible; real provider and integrated browser path are checked. |
| Server worker | `server/`, `tests/test_server*.py` | Durable bounded queue, deletion of 1–2, one active message lease per device, expiry/retry/restart recovery, idempotent ACKs, and local request guards pass tests. |
| Intelligence worker | `intelligence/`, `evals/`, `tests/test_intelligence*.py` | Validated GPT results, bounded WAV output, macOS speech option, clear demo mode, prompt-boundary and failure tests. |
| Mac interface worker | `web/index.html`, `web/styles.css`, `web/app.js` | One keyboard/on-screen action plays one message, successful audio completion ACKs it, stopping releases it; alerts never auto-speak. |
| Separate showcase chat | `web/showcase/` only | Minimalist student-focused product story, labeled concept assets, mock purchase with no payment/personal-data collection, and link to `/` for the Mac demo. |

Each brief must include the read-only requirement, deletion of 1–2 content after classification, fixed 3+ playback threshold, no automatic speech, dependency contracts, file ownership, validation requirements, and test commands. Work on scoped files in the shared checkout; do not overwrite another agent's changes or commit the entire working tree. Report what was tested, what was simulated, and what still needs physical access.

## Second wave

- Hardware integration, only when the teammate is ready: coordinate bridge firmware, actual iPhone capture, Pi audio/button, and reconnect tests. This does not block the current Mac milestone.
- Showcase integration: verify `/showcase/` serves the separate chat's page without overwriting it; the working Mac demo remains at `/`. Do not change the other chat's files without coordinating.
- Deployment agent: `deploy/`, Docker/configuration, persistent volume setup, TLS/reverse proxy, EC2 runbook, rollback instructions, secret configuration references. Coordinate actual account and host access before provisioning; do not guess AWS settings.
- Verification/demo agent: integration checks, live demo script, rubric alignment, measured latency/results, submission checklist, and backup-video outline. Independently assess the full user path after integration.
- Root continues integration and fixes cross-component failures. No new infrastructure services merely for architectural completeness.

## HTML product showcase

Recommendation for the eventual pitch: use completed hardware for the main demonstration, with a polished HTML page as a visual backdrop and a judge-accessible live entry point. While hardware is unfinished, show the actual Mac TTS path and label the input as sample/manual. Keep an obvious product path rather than a technical monitoring dashboard as the home screen.

Proposed headline: **Stay reachable. Stay present.** Supporting copy: "The notifications that matter, one button away." Working name SAP remains changeable.

One responsive page with four presentation states:

1. Hero: a clean photograph/render of the actual prototype, short headline, and one-sentence audience/problem statement. Show the benefit before the architecture.
2. Live story: clearly labeled source mode; incoming sample/consented demo notifications flow into the five priority levels; priorities 1–2 are discarded and only an aggregate discarded count remains, while 3–5 enter playback. Do not retain discarded notification content in the UI history. Display the actual server result in live mode. Never animate fake success while a real operation is pending or failed.
3. Hardware close-up: large readable current priority, pending count, and button/playback status. Leave space on the presentation screen for the team to hold up the physical device. A level-5 visual alert does not start speech.
4. Closing: one genuine user quote or observed result, proposed customer/channel, concise value proposition, project link, and interest form only if actually implemented. Do not invent testimonials or demand.

Optional small architecture illustration: phone → nearby bridge → server → pager, with a visible Bluetooth link and separate Wi-Fi links. Explain why the phone can remain put away. Build the diagram and status transitions in HTML/CSS/SVG for crisp, reliable playback. Support large-screen presentation, mobile, keyboard navigation, high contrast, and reduced motion.

Public visitors should be able to try a labeled sample-notification flow without needing the team's hardware. Keep this sandbox isolated from personal notifications and device control; protect/rate-limit any paid provider endpoint. Use a nonsecret read-only presentation session for live status. Never embed OpenAI keys or device tokens in public JavaScript. A static page with no working path alone is not the desired final submission.

## Higgsfield asset brief

User proposes using weekend Higgsfield access. Use it after the functional spine works, through its connected tools and applicable skill instructions when asset generation begins. No asset generation or publishing has been performed during planning.

Priority assets: one polished still and, if time permits, one 5–8 second silent looping product shot. Reference the actual hardware/prototype photos; preserve physical proportions and do not invent a display, controls, or other capabilities. Label any hypothetical enclosed device as a concept render. Use warm neutral surroundings, a restrained dark/cream palette, and one amber priority accent. Keep text outside generated media and render it as accessible HTML.

The hero loop should convey putting a phone down and checking a simple pager. It must not imply unsupported replies, microphone input, autonomous emergency assistance, or production readiness. Real footage of a real button triggering real sound is the evidence used in the demo. Keep a static fallback, local optimized asset files, a poster image, and explicit play/pause control; do not depend on an external generation service during the pitch.

Skip additional generations if core integration is slipping. Real prototype photography with good layout is sufficient.

## Four-minute pitch outline

| Time | What the audience sees and hears |
| --- | --- |
| 0:00–0:30 | Hero backdrop; identify one specific person, the distraction problem, and why ordinary notifications/Do Not Disturb do not meet that person's needs. Avoid claiming demand without evidence. |
| 0:30–1:00 | Show phone, bridge, and pager. One sentence on content-aware AI filtering. |
| 1:00–2:30 | Live processing: promotion is discarded; useful personal/team message queues; user presses the Mac playback button (physical button once ready) and hears it; immediate scenario triggers an alert and still waits for the button. Clearly label scripted sample content. |
| 2:30–3:15 | Real user feedback and measured behavior; distinguish current read-only prototype from future possibilities. |
| 3:15–4:00 | Customer/channel hypothesis and concise close. Invite judges to try the live page or physical button. |

Prepare answers about false classifications, privacy, missing iPhone previews, network failures, and hardware cost without pretending those issues are solved beyond tested behavior. Keep the under-two-minute challenge video focused on the same working path, not generated product footage alone.

## Submission preparation

Use [the event guide](https://cpvc-ai-hackathon-guide.vercel.app/#due) for deadlines and final requirements; confirm Discord updates manually. Track project-link submission, Sunday commitment, final live/project links, description, tool/open-source credits, optional challenge entry and its video, private-window link checks, and backup footage. Do not submit forms, send messages, or publish media as a side effect of planning.

API credits, EC2 expenses, asset-generation access, and artifact publishing remain separate operational concerns. Use existing authorized accounts when implementation starts and surface concrete access blockers rather than inventing credentials or deployment success.
