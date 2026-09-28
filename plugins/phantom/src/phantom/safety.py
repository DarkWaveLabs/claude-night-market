"""Safety controls: confirmation gates and action filtering.

Provides human-in-the-loop confirmation before dangerous actions
and region-based blocking to prevent clicking sensitive UI areas.

.. warning::
   ``always_approve`` and ``approve_clicks_only`` are *stubs* that
   always return ``True``. The aliases ``always_confirm`` and
   ``confirm_clicks_only`` are misnamed and DO NOT gate anything.
   Supply your own ``ConfirmCallback`` for real safety. The stubs
   exist only as test fixtures and should not be used in
   production paths (B-03).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

# Region = (x1, y1, x2, y2) top-left to bottom-right inclusive
Region = tuple[int, int, int, int]

# Confirmation callback: receives action dict, returns True to allow
ConfirmCallback = Callable[[dict[str, Any]], bool]


def no_confirm(action: dict[str, Any]) -> bool:
    """Always approve - no confirmation required.

    Use this when an explicit "no gating" semantic is desired.
    Prefer this over ``always_approve``/``always_confirm`` because
    its name accurately reflects behaviour.
    """
    return True


def always_approve(action: dict[str, Any]) -> bool:
    """Stub callback that always returns ``True``.

    .. warning::
       This is a no-op test fixture, not a safety gate. The
       function name is intentionally kept for backwards
       compatibility but should be read as "approve everything",
       not "always require approval". Pass a real
       ``ConfirmCallback`` (stdin prompt, GUI dialog, webhook)
       for actual human-in-the-loop confirmation. See B-03.
    """
    return True


# Backwards-compatible alias. Misnamed: this does NOT confirm anything;
# it returns True for all inputs. See module-level warning (B-03).
always_confirm = always_approve


def approve_clicks_only(action: dict[str, Any]) -> bool:
    """Stub callback that approves every action, click or not.

    .. warning::
       Like ``always_approve``, this is a no-op fixture. The name
       suggests it gates click actions, but the implementation
       returns ``True`` for clicks too. Replace with an
       interactive prompt for real click gating. See B-03.
    """
    click_actions = {
        "left_click",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "left_click_drag",
    }
    if action.get("action") not in click_actions:
        return True
    # Stub: approves clicks as well. Replace with interactive prompt.
    return True


# Backwards-compatible alias. Misnamed: this does NOT confirm clicks;
# it returns True for all clicks too. See module-level warning (B-03).
confirm_clicks_only = approve_clicks_only


#: Computer-tool actions that only observe the screen. Everything else
#: (clicks, typing, key presses, bash, file edits) is a side effect.
READ_ONLY_ACTIONS = frozenset({"screenshot", "cursor_position", "wait", "zoom"})

#: Set to "1" to run without prompts. Meant for the provided Docker
#: container, where the loop cannot reach the host.
UNATTENDED_ENV = "PHANTOM_UNATTENDED"


def terminal_confirm(action: dict[str, Any]) -> bool:
    """Ask on the controlling terminal before any side-effecting action.

    Read-only screen actions pass. With no terminal to ask on, the action
    is rejected: an unattended run has to opt in via ``PHANTOM_UNATTENDED``.
    """
    if action.get("tool", "computer") == "computer" and (
        action.get("action") in READ_ONLY_ACTIONS
    ):
        return True
    if not sys.stdin.isatty():
        return False
    shown = {k: v for k, v in action.items() if k != "text" or len(str(v)) < 200}
    try:
        reply = input(f"phantom wants to run {shown!r}. Allow? [y/N] ")
    except EOFError:
        return False
    return reply.strip().lower() in {"y", "yes"}


def default_confirm_callback() -> ConfirmCallback:
    """Pick the loop's gate: prompt by default, no gate only on opt-in."""
    if os.environ.get(UNATTENDED_ENV, "") == "1":
        return no_confirm
    return terminal_confirm


@dataclass
class SafetyConfig:
    """Configuration for safety controls."""

    require_confirmation: bool = False
    blocked_regions: list[Region] = field(default_factory=list)


class ActionFilter:
    """Block actions targeting forbidden screen regions.

    Useful for preventing clicks on sensitive UI areas like
    logout buttons, payment forms, or system controls.
    """

    def __init__(self, blocked_regions: Sequence[Region] = ()) -> None:
        self.blocked_regions = list(blocked_regions)

    def is_allowed(self, action: dict[str, Any]) -> bool:
        """Check if an action is allowed given blocked regions.

        Only coordinate-based actions (clicks, drags) are checked.
        Non-coordinate actions (type, key, screenshot) always pass.
        """
        coord = action.get("coordinate")
        if coord is None or len(coord) != 2:
            return True

        x, y = int(coord[0]), int(coord[1])

        for x1, y1, x2, y2 in self.blocked_regions:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return False

        return True


class ConfirmationGate:
    """Human-in-the-loop confirmation before executing actions.

    Wraps a callback function that receives the action dict and
    returns True (proceed) or False (reject). Tracks rejection
    counts for diagnostics.
    """

    def __init__(self, callback: ConfirmCallback = no_confirm) -> None:
        self.callback = callback
        self.rejection_count: int = 0
        self.approval_count: int = 0

    def check(self, action: dict[str, Any]) -> bool:
        """Check if the action is approved.

        Returns True if the callback approves, False if rejected.
        """
        approved = self.callback(action)
        if approved:
            self.approval_count += 1
        else:
            self.rejection_count += 1
        return approved
