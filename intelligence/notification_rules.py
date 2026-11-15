"""Exact device-event rules, applied before probabilistic classification."""

import re
import unicodedata
from dataclasses import dataclass

from contracts import NotificationInput

from .formatting import _source_label


def event_text(value: str) -> str:
    # ANCS labels may contain invisible direction/formatting marks.
    return " ".join("".join(c for c in value if unicodedata.category(c) != "Cf").split())


@dataclass(frozen=True)
class DeviceRule:
    priority: int
    kind: str
    spoken_text: str | None = None
    caller: str | None = None
    caller_key: str | None = None


def device_rule(notification: NotificationInput) -> DeviceRule | None:
    app = notification.app.casefold()
    body = event_text(notification.body)
    if app == "com.apple.findmy" and not notification.content_hidden:
        title = event_text(notification.title)
        routine_title = re.fullmatch(r"[1-9][0-9]* devices were left behind", title, re.IGNORECASE)
        routine_body = re.fullmatch(
            r"These devices are no longer detected near you\. "
            r"They were last seen near [^.!?]{1,180}\.", body, re.IGNORECASE,
        )
        if routine_title and routine_body and not event_text(notification.subtitle):
            return DeviceRule(2, "findmy_separation")
        # Unknown trackers, lost-mode updates and unfamiliar alerts remain classified.
        return None
    if app in {"com.toyopagroup.picaboo", "snapchat"}:
        if re.fullmatch(r"(?:.{1,120} )?is typing(?:\.{3}|…)?", body, re.IGNORECASE):
            return DeviceRule(1, "typing")
        sender = event_text(notification.title)
        if (body.casefold() == "sent you a chat" and sender
                and sender.casefold() not in {"snapchat", "unknown", "unknown sender"}
                and not event_text(notification.subtitle)
                and not notification.conversation_id and not notification.conversation_name
                and not notification.content_hidden):
            label = _source_label(sender, 120)
            return DeviceRule(3, "snapchat_chat", f"On Snapchat, {label} sent you a message.", label)
        # Only the observed one-to-one chat template is eligible for speech.
        # Unknown/new formats fail closed rather than being promoted by the LLM.
        return DeviceRule(2, "snapchat_other")
    if app != "com.apple.mobilephone" or notification.content_hidden:
        return None
    kind = {"incoming call": "incoming", "missed call": "missed"}.get(body.casefold())
    if kind is None:
        return None
    if kind == "incoming":
        # Ringing is transient; only a subsequent missed-call event is actionable.
        return DeviceRule(2, kind)
    caller = event_text(notification.sender or notification.title)
    if caller.casefold() in {"", "phone", "incoming call", "missed call", "unknown",
                            "unknown caller", "no caller id", "private number",
                            "private caller", "blocked", "restricted", "wireless caller"}:
        caller = ""
    # ANCS supplies a display label, not a contacts-membership flag. A named label
    # is our contact proxy; raw phone numbers and Siri's "Maybe:" guesses stay P3.
    named = (any(character.isalpha() for character in caller)
             and not re.fullmatch(r"[+\d\s().-]+(?:\s*(?:ext\.?|x)\s*\d+)?", caller, re.I)
             and not caller.casefold().startswith("maybe:"))
    label = _source_label(caller, 120) if caller else "an unknown caller"
    return DeviceRule(
        4 if named else 3, kind, f"Missed call from {label}.",
        label if caller else None, caller.casefold() if caller else None,
    )
