"""Keyboard prompt and graceful-stop controls."""
from __future__ import annotations

import logging
import os
import select
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .errors import ForcedTermination
from .ffmpeg import terminate_active_external_processes

class KeyboardController:
    """Monitor q/p/Ctrl+C requests without interrupting active file transactions."""

    PAUSE_REQUEST_MESSAGE = "Pause requested.\nCurrent book will finish processing before pausing."
    QUIT_REQUEST_MESSAGE = "Quit requested.\nCurrent book will finish processing before prompting for exit."

    def __init__(self) -> None:
        self.pause_requested = False
        self.quit_requested = False
        self._stop_event = threading.Event()
        self._prompt_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._previous_sigint_handler: Any = None
        self._active_temp_files: set[Path] = set()

    def start(self) -> None:
        """Start daemon keyboard monitoring and install graceful Ctrl+C handling."""

        self._previous_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)
        self._thread = threading.Thread(target=self._monitor_keyboard, name="keyboard-monitor", daemon=True)
        self._thread.start()
        logging.info("Keyboard controls enabled: q=quit, p=pause, Ctrl+C=graceful quit")

    def stop(self) -> None:
        """Stop monitoring, join the monitor thread, and restore the previous Ctrl+C handler."""

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._previous_sigint_handler is not None:
            signal.signal(signal.SIGINT, self._previous_sigint_handler)

    def restore_terminal(self) -> None:
        """Defensively restore terminal echo/canonical mode if stdin is a TTY.

        Safe to call multiple times.  Logs attempts and failures.
        """
        if os.name == "nt" or not sys.stdin.isatty():
            return
        try:
            import termios

            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            # Re-enable echo and canonical (line-buffered) input.
            attrs[3] |= termios.ECHO | termios.ICANON
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
            logging.info("Terminal settings restored")
        except Exception:
            logging.warning("Failed to restore terminal settings", exc_info=True)

    def request_pause(self) -> None:
        with self._lock:
            should_notify = not self.pause_requested
            self.pause_requested = True
        if should_notify:
            self._display_request_message(self.PAUSE_REQUEST_MESSAGE)
        logging.info("Pause requested by keyboard input")

    def request_quit(self, source: str) -> None:
        with self._lock:
            if self.quit_requested:
                logging.critical("Forced termination requested by %s after graceful quit was already pending", source)
                self.best_effort_cleanup()
                if threading.current_thread() is threading.main_thread():
                    raise ForcedTermination("Forced termination requested")
                os.kill(os.getpid(), signal.SIGINT)
                raise ForcedTermination("Forced termination requested")
            self.quit_requested = True
        self._display_request_message(self.QUIT_REQUEST_MESSAGE)
        logging.warning("Graceful quit requested by %s", source)

    @staticmethod
    def _display_request_message(message: str) -> None:
        print(f"⚠️ {message}", flush=True)

    def clear_pause(self) -> None:
        with self._lock:
            self.pause_requested = False

    def clear_quit(self) -> None:
        with self._lock:
            self.quit_requested = False

    def register_temp_file(self, path: Path) -> None:
        with self._lock:
            self._active_temp_files.add(path)

    def unregister_temp_file(self, path: Path) -> None:
        with self._lock:
            self._active_temp_files.discard(path)

    def best_effort_cleanup(self) -> None:
        """Attempt to remove currently known temporary outputs."""

        terminate_active_external_processes()
        with self._lock:
            temp_files = tuple(self._active_temp_files)
        for temp_file in temp_files:
            try:
                temp_file.unlink(missing_ok=True)
                logging.info("Cleaned temporary file during forced termination: %s", temp_file)
            except OSError:
                logging.exception("Failed to clean temporary file during forced termination: %s", temp_file)

    def prompt_section(self) -> "KeyboardPromptSection":
        return KeyboardPromptSection(self)

    def _handle_sigint(self, signum: int, frame: object) -> None:
        del signum, frame
        self.request_quit("Ctrl+C")

    def _monitor_keyboard(self) -> None:
        if os.name == "nt":
            self._monitor_windows_keyboard()
        else:
            self._monitor_posix_keyboard()

    def _handle_key(self, key: str) -> None:
        if key.casefold() == "p":
            self.request_pause()
        elif key.casefold() == "q" or key == "\x03":
            self.request_quit("keyboard" if key.casefold() == "q" else "Ctrl+C")

    def _monitor_windows_keyboard(self) -> None:
        try:
            import msvcrt
        except ImportError:
            logging.warning("msvcrt unavailable; keyboard controls disabled")
            return

        while not self._stop_event.is_set():
            if self._prompt_event.is_set():
                time.sleep(0.1)
                continue
            if msvcrt.kbhit():
                raw = msvcrt.getwch()
                self._handle_key(raw)
            time.sleep(0.1)

    def _monitor_posix_keyboard(self) -> None:
        if not sys.stdin.isatty():
            logging.info("stdin is not a TTY; keyboard controls disabled")
            return

        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while not self._stop_event.is_set():
                if self._prompt_event.is_set():
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    while self._prompt_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.1)
                    tty.setcbreak(fd)
                    continue
                readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                if readable:
                    self._handle_key(sys.stdin.read(1))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

class KeyboardPromptSection:
    """Temporarily pause background keyboard reads while normal input() is used."""

    def __init__(self, controller: KeyboardController) -> None:
        self.controller = controller

    def __enter__(self) -> None:
        self.controller._prompt_event.set()
        time.sleep(0.05)

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.controller._prompt_event.clear()
