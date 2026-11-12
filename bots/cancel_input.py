"""Cancel anywhere in the launcher and console prompts.

Every rich Prompt / Confirm / IntPrompt / FloatPrompt in this process:
  - shows a dim "(q = back)" hint,
  - raises CancelInput when the answer is q, back, esc or an Esc character,
  - leaves Ctrl+C alone: in a terminal it means stop, so it keeps its normal behaviour.
Callers catch CancelInput and return to the previous menu without saving.
choose() reads one key on a Windows terminal (Esc / q = back, Enter = default).
"""
from __future__ import annotations

import os
import sys

from rich.prompt import Confirm, PromptBase
from rich.text import Text

CANCEL_WORDS = ("q", "back", "esc", "\x1b")
HINT = " (q = back)"


FORCE_PROMPT = False   # tests: route choose() through Prompt (scriptable) instead of msvcrt


class CancelInput(Exception):
    """The user backed out of a prompt. Nothing typed so far is saved."""


def is_cancel(value) -> bool:
    return isinstance(value, str) and (value.strip() in CANCEL_WORDS or "\x1b" in value)


def _wrap_process(cls) -> None:
    orig = cls.__dict__.get("process_response")
    if orig is None or getattr(orig, "_cancel_wrapped", False):
        return

    def process_response(self, value, _o=orig):
        if is_cancel(value):
            raise CancelInput()
        return _o(self, value)
    process_response._cancel_wrapped = True
    cls.process_response = process_response


def install() -> None:
    if getattr(PromptBase, "_cancel_installed", False):
        return
    _wrap_process(PromptBase)
    _wrap_process(Confirm)
    orig_call = PromptBase.__call__

    def __call__(self, *a, **k):
        try:
            if isinstance(self.prompt, Text) and HINT not in self.prompt.plain:
                self.prompt = self.prompt + Text(HINT, style="dim")
        except Exception:
            pass
        try:
            return orig_call(self, *a, **k)
        except EOFError:          # input closed (no terminal): treat as back. Ctrl+C is NOT caught.
            raise CancelInput()
    PromptBase.__call__ = __call__
    PromptBase._cancel_installed = True


def choose(console, prompt: str, choices: list, default: str) -> str:
    """One-key choice. Windows terminal: Esc / q = back, Enter = default. Elsewhere: a normal prompt."""
    if os.name == "nt" and sys.stdin.isatty() and not FORCE_PROMPT:
        try:
            import msvcrt
        except ImportError:
            msvcrt = None
        if msvcrt:
            console.print(f"{prompt} [dim][{'/'.join(choices)}] ({default}) Esc/q = back[/] ", end="")
            while True:
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    msvcrt.getwch(); continue
                if ch in ("\r", "\n"):
                    console.print(default); return default
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x1b", "q", "Q"):
                    console.print("back"); raise CancelInput()
                if ch in choices:
                    console.print(ch); return ch
    from rich.prompt import Prompt
    return Prompt.ask(prompt, choices=list(choices), default=default, console=console)


install()
