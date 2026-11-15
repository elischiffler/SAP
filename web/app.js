const requestTimeout = 10_000;
const receivedTimeFormat = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const statuses = {
  pending: "Processing",
  ready: "Ready",
  leased: "Playing / held",
  failed: "Failed",
};
const ingressQueueLabels = {
  ...statuses,
  played: "Played",
  discarded: "Discarded",
  unavailable: "Unavailable",
};
const byId = (id) => document.getElementById(id);
let audioContext;
let chimeFailed = false;
let seenAlerts = new Set();
let alertBaselineLoaded = false;
let pollInProgress = false;
let ingressSignature;
let historyCursor = null;
let historyNextCursor = null;
const historyBack = [];
let pollTimer;
let queueSignature;
const retrying = new Set();

function setText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function feedback(id, message, isError = false) {
  const element = byId(id);
  setText(element, message);
  element.dataset.state = isError ? "error" : "normal";
  element.hidden = !message;
}

class HttpError extends Error {
  constructor(response) {
    super("HTTP " + response.status);
    this.status = response.status;
  }
}

async function withResponse(path, options, read, controller = new AbortController()) {
  const timer = setTimeout(() => controller.abort(), requestTimeout);
  try {
    const response = await fetch(path, {
      cache: "no-store",
      redirect: "error",
      ...options,
      signal: controller.signal,
    });
    if (!response.ok) throw new HttpError(response);
    return await read(response);
  } finally {
    clearTimeout(timer);
  }
}

function getJson(path) {
  return withResponse(path, {}, (response) => response.json());
}

function postJson(path, body = {}) {
  return withResponse(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, (response) => response.json());
}

function statusMessage(error) {
  return error instanceof HttpError ? "HTTP " + error.status : "connection or browser error";
}

function unlockChime() {
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) throw new Error("Audio context unsupported");
    audioContext ??= new Context();
    return audioContext.resume().then(() => {
      chimeFailed = audioContext.state !== "running";
      renderChime();
      return !chimeFailed;
    }, () => {
      chimeFailed = true;
      renderChime();
      return false;
    });
  } catch {
    chimeFailed = true;
    renderChime();
    return Promise.resolve(false);
  }
}

function playChime() {
  if (audioContext?.state !== "running") return;
  try {
    const tone = audioContext.createOscillator();
    const gain = audioContext.createGain();
    const start = audioContext.currentTime;
    tone.frequency.setValueAtTime(660, start);
    tone.frequency.setValueAtTime(880, start + 0.14);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.12, start + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.34);
    tone.connect(gain);
    gain.connect(audioContext.destination);
    tone.start(start);
    tone.stop(start + 0.36);
    tone.onended = () => {
      tone.disconnect();
      gain.disconnect();
    };
  } catch {
    chimeFailed = true;
    renderChime();
  }
}

function renderChime() {
  const enabled = !chimeFailed && audioContext?.state === "running";
  byId("enable-chimes").hidden = enabled;
  setText(byId("alert-hint"), enabled
    ? "Speech starts when you press the pager button."
    : chimeFailed
      ? "The chime is unavailable. The visible alert stays active."
      : "Enable sound to hear a chime for new alerts. Speech waits for the pager button.");
}

function renderAlerts(alerts) {
  const current = new Set(alerts.map((alert) => alert.id));
  const arrived = alertBaselineLoaded && alerts.some((alert) => !seenAlerts.has(alert.id));
  seenAlerts = current;
  alertBaselineLoaded = true;
  const title = current.size === 1 ? "Priority 5 alert" : current.size + " priority 5 alerts";
  byId("priority-alert").hidden = current.size === 0;
  setText(byId("alert-title"), title);
  if (!current.size || arrived) setText(byId("alert-announcement"), arrived ? title : "");
  renderChime();
  if (arrived) playChime();
}

function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function priorityBadge(priority) {
  const badge = createElement("span", "priority", "P" + priority);
  badge.dataset.priority = priority;
  badge.setAttribute("aria-label", "Priority " + priority);
  return badge;
}

function sourceLabel(item) {
  const contact = item.conversation_name || item.sender;
  return item.app + (contact ? " · " + contact : "");
}

function notificationCountLabel(item) {
  return item.notification_count > 1 ? item.notification_count + " notifications" : "";
}

function renderQueue(items) {
  const current = items.filter((item) => Object.hasOwn(statuses, item.status)
    && ![1, 2].includes(item.priority))
    .map((item) => item.status === "pending" && !item.priority
      ? { id: item.id, app: "Incoming notification", status: item.status, received_at: item.received_at }
      : item);
  // Preserve focus and pending retry controls across unchanged polls.
  const signature = JSON.stringify(current);
  if (signature === queueSignature) return;
  queueSignature = signature;
  const focusedRetry = document.activeElement?.dataset.messageId;
  const queue = byId("queue");
  const fragment = document.createDocumentFragment();
  for (const item of current) {
    const row = createElement("li");
    const heading = createElement("div", "row-heading");
    if (item.priority) heading.append(priorityBadge(item.priority));
    const source = sourceLabel(item);
    heading.append(createElement("strong", "", source));
    const count = notificationCountLabel(item);
    if (count) heading.append(createElement("span", "notification-count", count));
    heading.append(createElement("span", "row-status", statuses[item.status]));
    row.append(heading);
    const received = new Date(item.received_at ?? "");
    if (Number.isFinite(received.getTime())) {
      const timestamp = createElement("time", "received-time", "Received " + receivedTimeFormat.format(received));
      timestamp.dateTime = received.toISOString();
      timestamp.title = timestamp.dateTime;
      row.append(timestamp);
    }
    if (item.spoken_text) row.append(createElement("p", "row-body", item.spoken_text));
    if (item.error) row.append(createElement("p", "row-error", item.error));
    if (item.status === "failed") {
      const retry = createElement("button", "quiet-button row-retry", "Retry");
      retry.type = "button";
      retry.dataset.messageId = item.id;
      retry.disabled = retrying.has(item.id);
      retry.setAttribute("aria-label", "Retry " + source);
      retry.addEventListener("click", () => retryMessage(item.id, retry));
      row.append(retry);
    }
    fragment.append(row);
  }
  queue.replaceChildren(fragment);
  if (focusedRetry) {
    Array.from(queue.querySelectorAll("button")).find((button) => button.dataset.messageId === focusedRetry)?.focus();
  }
  byId("empty").hidden = current.length > 0;
  setText(byId("empty"), "No notifications in the playback queue.");
}

function setConnection(state, message) {
  const connection = byId("connection");
  connection.dataset.state = state;
  setText(connection, message);
}

async function refreshIngress() {
  try {
    const requestedCursor = historyCursor;
    const path = "/api/ingress-log?limit=50" + (requestedCursor === null ? "" : "&before=" + requestedCursor);
    const { entries, total, next_cursor } = await getJson(path);
    if (requestedCursor !== historyCursor) return;
    historyNextCursor = next_cursor;
    byId("history-newer").disabled = historyBack.length === 0;
    byId("history-older").disabled = next_cursor === null;
    setText(byId("ingress-count"), String(total) + " requests");
    const encoded = new TextEncoder().encode(JSON.stringify(entries));
    const hash = await crypto.subtle.digest("SHA-256", encoded);
    const signature = Array.from(new Uint8Array(hash)).join(",");
    if (signature !== ingressSignature) {
      const list = byId("ingress-entries");
      const expanded = new Set(Array.from(list.querySelectorAll("details[open]"), (details) => details.dataset.requestId));
      const focused = document.activeElement?.closest(".ingress-payload")?.dataset.requestId;
      const fragment = document.createDocumentFragment();
      for (const entry of entries) {
        const row = createElement("li");
        const heading = createElement("div", "ingress-request");
        const status = createElement("span", "ingress-status", String(entry.status_code));
        status.toggleAttribute("data-error", entry.status_code >= 400);
        status.setAttribute("aria-label", "HTTP " + entry.status_code);
        const route = createElement("code", "", entry.method + " " + entry.path);
        const received = new Date(entry.received_at);
        const time = createElement("time", "ingress-time", receivedTimeFormat.format(received));
        time.dateTime = received.toISOString();
        time.title = time.dateTime;
        if (entry.priority != null) heading.append(priorityBadge(entry.priority));
        else heading.append(createElement("span", "ingress-source", entry.queue_status === "pending" ? "Classifying" : "Priority unavailable"));
        heading.append(status, route, time);
        row.append(heading);
        const eventId = entry.event_id ? "Event " + entry.event_id.slice(0, 8) : "";
        const queueStatus = Object.hasOwn(ingressQueueLabels, entry.queue_status)
          ? ingressQueueLabels[entry.queue_status]
          : "";
        const source = [entry.app_label || entry.app, eventId, queueStatus].filter(Boolean).join(" · ");
        if (source) row.append(createElement("p", "ingress-source", source));
        if (entry.error) row.append(createElement("p", "row-error", entry.error));
        if (entry.status_code === 202 && entry.payload) {
          const details = createElement("details", "ingress-payload");
          details.dataset.requestId = entry.id;
          details.open = expanded.has(String(entry.id));
          const payload = typeof entry.payload === "string"
            ? entry.payload
            : JSON.stringify(entry.payload, null, 2);
          const content = createElement("pre", "", payload);
          content.tabIndex = 0;
          details.append(createElement("summary", "", entry.payload_redacted ? "Received payload (sensitive values redacted)" : "Received payload"), content);
          row.append(details);
        } else if (entry.payload_expired || entry.queue_status === "discarded" || entry.queue_status === "played") {
          row.append(createElement("p", "ingress-source", entry.payload_expired ? "Payload expired after two hours." : "Payload unavailable for this older request."));
        }
        fragment.append(row);
      }
      list.replaceChildren(fragment);
      if (focused) {
        Array.from(list.querySelectorAll(".ingress-payload"))
          .find((details) => details.dataset.requestId === focused)?.querySelector("summary").focus();
      }
      ingressSignature = signature;
    }
    feedback("ingress-feedback", entries.length ? "" : "No incoming requests yet.");
  } catch (error) {
    for (const details of byId("ingress-entries").querySelectorAll(".ingress-payload")) details.remove();
    ingressSignature = undefined;
    feedback("ingress-feedback", "Couldn’t refresh incoming requests (" + statusMessage(error) + "). Retrying…", true);
  }
}

async function refreshState() {
  try {
    const state = await getJson("/api/state");
    renderAlerts(state.alerts);
    renderQueue(state.items);
    setText(byId("queue-count"), state.counts.ready + " ready");
    for (const field of ["pending"]) {
      setText(byId("count-" + field), String(state.counts[field]));
    }
    const classifier = state.providers.classifier;
    const speechProvider = state.providers.tts;
    setText(byId("classifier"), "Classifier · " + ({ openai: "Live GPT", demo: "Demo mode" }[classifier] || classifier));
    setText(byId("speech"), "Voice · " + ({ openai: "Alloy (OpenAI AI-generated speech)", macos: "macOS speech" }[speechProvider] || speechProvider));
    const limits = state.limits;
    setText(byId("budget"), "Provider calls · " + limits.provider_calls + " / " + limits.max_provider_calls);
    feedback("state-error", "");
    setConnection("online", "Connected");
  } catch (error) {
    setConnection("offline", "Disconnected");
    feedback("state-error", "Couldn’t refresh the queue (" + statusMessage(error) + "). Reconnecting…", true);
  }
}

async function refreshPi() {
  try {
    const state = await getJson("/api/pi/status");
    setText(byId("pi-connection"), state.connected ? "Connected" : state.last_seen ? "No recent contact" : "Waiting for Pi");
    feedback("pi-feedback", state.last_seen
      ? "Last contact " + receivedTimeFormat.format(new Date(state.last_seen))
      : "No Pi contact yet. One message is offered per button press.");
    const labels = {
      downloading: "Sending audio",
      awaiting_ack: "Audio sent · Pi download not yet confirmed",
      acknowledged: "Pi acknowledged completion",
      failed: "Audio transfer failed",
      expired: "Acknowledgment timed out · retry needed",
    };
    const fragment = document.createDocumentFragment();
    for (const transfer of state.transfers) {
      const confirmed = transfer.download_confirmed_at;
      const label = transfer.status === "awaiting_ack" && confirmed
        ? "Downloaded on Pi · awaiting playback acknowledgment"
        : (labels[transfer.status] || transfer.status);
      const row = createElement("li", "", label
        + " · " + transfer.message_id.slice(0, 8)
        + " · " + receivedTimeFormat.format(new Date(transfer.updated_at)));
      row.dataset.status = transfer.status;
      if (confirmed) {
        row.append(createElement("p", "pi-receipt", "Pi confirmed saved WAV · "
          + receivedTimeFormat.format(new Date(confirmed))));
      }
      if (transfer.spoken_text) {
        const details = [transfer.app, transfer.sender,
          transfer.priority ? "Priority " + transfer.priority : null].filter(Boolean);
        row.append(createElement("p", "pi-message-meta", details.join(" · ")));
        row.append(createElement("p", "pi-message-text", transfer.spoken_text));
      } else {
        row.append(createElement("p", "pi-message-meta", transfer.status === "acknowledged"
          ? "Message content removed after playback acknowledgment."
          : "Message text is no longer available."));
      }
      fragment.append(row);
    }
    if (!state.transfers.length) {
      fragment.append(createElement("li", "", "No audio transfers yet. A button press downloads one message."));
    }
    byId("pi-transfers").replaceChildren(fragment);
  } catch (error) {
    setText(byId("pi-connection"), "Unavailable");
    feedback("pi-feedback", "Couldn’t refresh Pi delivery status. Retrying…", true);
  }
}

async function pollState() {
  if (pollInProgress) return;
  clearTimeout(pollTimer);
  pollInProgress = true;
  try {
    await Promise.allSettled([refreshState(), refreshIngress(), refreshPi()]);
  } finally {
    pollInProgress = false;
    pollTimer = setTimeout(pollState, 2_000);
  }
}

async function retryMessage(messageId, button) {
  if (retrying.has(messageId)) return;
  retrying.add(messageId);
  button.disabled = true;
  feedback("queue-error", "");
  try {
    await postJson("/api/messages/" + encodeURIComponent(messageId) + "/retry");
  } catch (error) {
    feedback("queue-error", "Couldn’t retry the message (" + statusMessage(error) + ").", true);
  } finally {
    retrying.delete(messageId);
    const buttons = byId("queue").querySelectorAll("button");
    Array.from(buttons).filter((candidate) => candidate.dataset.messageId === messageId)
      .forEach((candidate) => { candidate.disabled = false; });
    void pollState();
  }
}

byId("history-older").addEventListener("click", () => {
  if (historyNextCursor === null) return;
  historyBack.push(historyCursor);
  historyCursor = historyNextCursor;
  ingressSignature = undefined;
  void pollState();
});
byId("history-newer").addEventListener("click", () => {
  if (!historyBack.length) return;
  historyCursor = historyBack.pop();
  ingressSignature = undefined;
  void pollState();
});

byId("enable-chimes").addEventListener("click", () => {
  void unlockChime().then((enabled) => { if (enabled) playChime(); });
});
window.addEventListener("online", () => void pollState());
void pollState();
