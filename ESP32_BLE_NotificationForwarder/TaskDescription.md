# Project Overview: Phone-Free Notification Companion
 
Last updated: 2026-11-14 (hackathon weekend, Day 1)
 
## Context
- Cal Poly vibe-coding hackathon sponsored by OpenAI. Goal: a product that helps people and would break without AI. Judging emphasizes helping people, especially disadvantaged groups.
- Resources: Raspberry Pi 4, Raspberry Pi Zero 2W (the marketed device), ESP32s (Seeed XIAO ESP32-C3 confirmed, has BLE), Arduino kit, Claude + Codex Pro, AWS t3a.medium EC2.
- Working preference: short, direct answers. Fast iteration. MVP first ("water through the pipes"), no over-engineering.
## Concept
A small physical device that lets a user keep their phone out of reach (to avoid doomscrolling) without missing important things. A button on the device reads out only the important/time-sensitive notifications (Slack, Discord, email, iMessage, calls) via TTS. An LED signals that something important is waiting.
 
Pitch the smart triage (AI judging urgency), not the gadget. Competitors: iOS/Android Focus modes with allow-lists, OS AI notification summaries, smartwatches, Light Phone, and failed AI gadgets (Humane Pin, Rabbit R1). Differentiation must be urgency understanding beyond allow-lists, and no screen/app temptation.
 
Possible audience angles for judging: people with ADHD or compulsive phone use, on-call workers, caregivers who must stay reachable.
 
## Architecture
```
iPhone --BLE (ANCS)--> ESP32-C3 (kept near phone) --WiFi/HTTP POST--> EC2 server
EC2: notification -> LLM API (score 1-3) -> if important: TTS -> audio buffer
Pi Zero 2W (button, speaker, LED) --WiFi--> EC2: fetch buffered audio, play
```
- ESP32 acts as an ANCS (Apple Notification Center Service) client. This is why iMessage works: ANCS delivers all notifications the phone shows. Reading notifications directly from Slack/Discord/Gmail APIs was the earlier alternative and is the fallback.
- Server: receives JSON, scores with LLM, generates TTS per important notification, stores in buffer.
- Priority scheme (team design): scores 1-3 go in the buffer; 1 also flashes the LED; LED stays on when buffer passes a threshold. Weights considered: source app, message vs call, semantic content, source contact.
- Pi: on button press requests buffered audio and plays it.
## Decisions made by the team
- Include iMessage via ANCS on ESP32 (not just Slack/Discord/email).
- Server precomputes TTS audio so button press feels instant.
- Pi Zero 2W is the physical product; ESP32 is a phone-side bridge.
- ESP32 firmware is MVP-only: hardcoded config, BLE + Wi-Fi reconnect, fire-and-forget POST. No retry queue, no mock server, no extra features. A first Claude Code attempt produced a 700-line file; that was rejected as over-complicated.
## Recommendations from Claude (not yet confirmed as decisions)
- Do not clear the server buffer on fetch. Pi should ack after playback, then delete.
- LED needs a way to get updates: Pi polls the server every few seconds (simplest) or holds an open connection.
- Consider batching into one summary clip at press time instead of N clips.
- Skip model fine-tuning. Use base prompt + few-shot examples + VIP contact list that forces priority 1; LLM returns the 1-3 score, simple rules override.
- Build a ~30-item labeled test set of sample notifications to show filter accuracy to judges.
- Proposed split: Person A ESP32/ANCS, Person B server + LLM + TTS, Person C Pi button/LED/speaker.
- Pi Zero 2W has no audio jack: needs I2S amp (e.g. MAX98357A) or USB/Bluetooth speaker.
- Campus/venue Wi-Fi (captive portal or enterprise login) can break ESP32/Pi: bring a travel router or use a phone hotspot.
## Known risks (verify early, ANCS not yet tested on this hardware)
1. ANCS bonding and reconnect reliability after phone sleep/out of range.
2. iOS "Share System Notifications" toggle must be enabled for the device in Bluetooth settings.
3. Message previews must be on or message text may be empty.
4. Test whether notifications still arrive during Focus modes.
5. Calls arrive as notifications (caller name) and can be announced, but cannot be answered via ANCS.
6. Privacy: notification text goes to LLM and TTS APIs.
7. Design risk: a "check anything new?" button can become a compulsive habit.
## ESP32 firmware spec (MVP, give this to Claude Code)
 
Goal: iPhone gets a notification -> ESP32 gets it over BLE (ANCS) -> ESP32 POSTs it to the server over Wi-Fi. Nothing more.
 
Setup
- Seeed XIAO ESP32-C3, PlatformIO in VS Code, Arduino framework, NimBLE-Arduino.
- Two files only: `src/main.cpp` and `include/config.h`.
- Keep it minimal. Aim for roughly 200 lines. No classes or abstractions beyond what NimBLE callbacks require.
config.h (hardcoded)
- `WIFI_SSID`, `WIFI_PASS`, `SERVER_URL`
BLE / ANCS
- Advertise as a peripheral with ANCS service solicitation so the iPhone connects. Enable bonding/encryption (NimBLE default bond storage is fine).
- On connect: find the ANCS service, subscribe to Notification Source and Data Source.
- On a Notification Source "added" event: skip if the PreExisting flag is set; otherwise write a Get Notification Attributes command to Control Point for: App Identifier, Title, Message (max ~200), Date.
- Parse the Data Source response (it can span multiple packets; a simple byte buffer is enough).
- On disconnect: restart advertising.
- UUIDs (verify): Service 7905F431-B5CE-4E99-A40F-4B1E122D00D0; Notification Source 9FBF120D-6301-42D9-8C58-25E699A21DBD; Control Point 69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9; Data Source 22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB.
Wi-Fi / HTTP
- Connect on boot; in `loop()`, reconnect if disconnected.
- POST JSON to `SERVER_URL`: `{"app":"...","title":"...","message":"...","date":"..."}`
- Fire-and-forget: log the HTTP status to Serial, no retries.
- Do the POST in `loop()`, not inside BLE callbacks (callbacks just copy the parsed notification into a small fixed-size pending list; dropping extras is acceptable).
Logging
- Serial at 115200: BLE connect/disconnect, each parsed notification, POST status.
Out of scope
- Retry queue, mock server, dedup, removed/modified events, flags/categories, LED, call handling, runtime config, README.
Done when
- `pio run -t upload` works, phone pairs, and sending a test iMessage/Slack/email to the phone produces a POST with the right app/title/message/date within a couple seconds.
## Ideas considered and set aside
Earlier brainstorming (accessibility, dementia, pets, website-simplifier overlay, bill-fighting, hold-for-me agent, home sensors, etc.) was explored and not pursued. Top earlier picks were PaperPal (AI mail reader box), Loop Companion (dementia answers), SoundSight (sound alerts for Deaf users), and a hold-for-me phone agent. Jake chose the notification companion.
 
## Open questions
- Is Pi Zero 2W audio hardware available?
- Exact pitch angle for the "helps people" criterion.