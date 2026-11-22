"""Running 7z.exe without freezing the window: progress, prompts, pause, cancel.

A Job runs one or more steps in order. A step is either a 7z command line or a Python callable
(for PR7-Z's own work around 7z, e.g. moving files out of a staging folder). Overwrite and
password questions from 7z are passed to callbacks the UI provides, and the answer is typed
back to 7z, exactly as 7-Zip's own GUI does.
"""

from __future__ import annotations

import codecs
import time
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from . import engine
from .engine import Event, ProgressParser

try:  # pause / background priority; optional
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


@dataclass
class Step:
    label: str
    args: list[str] | None = None            # a 7z command line ...
    func: Callable[["Job"], None] | None = None  # ... or Python work
    cwd: str | None = None
    weight: float = 1.0                       # share of the overall progress bar
    ok_codes: tuple = (0,)
    on_done: Callable[[int], None] | None = None


@dataclass
class Result:
    code: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cancelled: bool = False
    log: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.errors and not self.cancelled


class Job(QObject):
    progress = Signal(float)        # 0..100 over all steps
    current_file = Signal(str)
    step_started = Signal(str)
    total_bytes = Signal(int)
    error = Signal(str)
    finished = Signal(object)       # Result

    def __init__(self, title: str, steps: list[Step], parent=None):
        super().__init__(parent)
        self.title = title
        self.steps = steps
        self.result = Result()
        self.ask_overwrite: Callable[[dict], str] = lambda q: "quit"
        self.ask_password: Callable[[], str | None] = lambda: None
        self.files_done = 0
        self.started_at = 0.0
        self.paused_for = 0.0
        self._pause_start = 0.0
        self._i = -1
        self._proc: QProcess | None = None
        self._parser = ProgressParser()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._busy = False
        self._cancelled = False
        self.paused = False
        self._step_pct = 0.0

    # ------------------------------------------------------------ control
    def start(self):
        self.started_at = time.monotonic()
        QTimer.singleShot(0, self._next)

    def cancel(self):
        self._cancelled = True
        self.result.cancelled = True
        if self.paused:
            self.set_paused(False)
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def set_paused(self, paused: bool):
        p = self._psutil()
        if p is None or paused == self.paused:
            return
        try:
            (p.suspend if paused else p.resume)()
        except Exception:
            return
        self.paused = paused
        if paused:
            self._pause_start = time.monotonic()
        else:
            self.paused_for += time.monotonic() - self._pause_start

    def set_background(self, on: bool):
        p = self._psutil()
        if p is None:
            return
        try:
            if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if on else psutil.NORMAL_PRIORITY_CLASS)
            else:
                p.nice(10 if on else 0)
        except Exception:
            pass

    def elapsed(self) -> float:
        now = self._pause_start if self.paused else time.monotonic()
        return max(0.0, now - self.started_at - self.paused_for)

    def _psutil(self):
        if psutil is None or not self._proc or self._proc.state() == QProcess.NotRunning:
            return None
        try:
            return psutil.Process(self._proc.processId())
        except Exception:
            return None

    # ------------------------------------------------------------ steps
    def _overall(self, step_pct: float) -> float:
        total = sum(s.weight for s in self.steps) or 1.0
        done = sum(s.weight for s in self.steps[:self._i])
        return min(100.0, 100.0 * (done + self.steps[self._i].weight * step_pct / 100.0) / total)

    def _next(self):
        if self._cancelled:
            return self._finish()
        self._i += 1
        if self._i >= len(self.steps):
            return self._finish()
        step = self.steps[self._i]
        self._step_pct = 0.0
        self.step_started.emit(step.label)
        if step.func is not None:
            try:
                step.func(self)
            except Exception as e:  # report and stop
                self.result.errors.append(str(e))
                self.result.code = 2
                self.error.emit(str(e))
                return self._finish()
            self.progress.emit(self._overall(100))
            if step.on_done:
                step.on_done(0)
            QTimer.singleShot(0, self._next)
            return
        self._parser = ProgressParser()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        p = QProcess(self)
        self._proc = p
        if step.cwd:
            p.setWorkingDirectory(step.cwd)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(self._done)
        p.errorOccurred.connect(self._proc_error)
        p.start(step.args[0], step.args[1:])

    def _proc_error(self, err):
        if err == QProcess.FailedToStart:
            self.result.errors.append(f"Couldn't start 7-Zip: {self.steps[self._i].args[0]}")
            self.result.code = 2
            self._finish()

    def _read(self):
        if self._busy:  # a prompt dialog is open; the rest is read after it's answered
            return
        self._busy = True
        try:
            while self._proc and self._proc.bytesAvailable():
                data = bytes(self._proc.readAllStandardOutput())
                text = self._decoder.decode(data)
                for ev in self._parser.feed(text):
                    self._handle(ev)
        finally:
            self._busy = False

    def _handle(self, ev: Event):
        if ev.kind == "percent":
            self._step_pct = float(ev.value)
            self.progress.emit(self._overall(self._step_pct))
        elif ev.kind == "file":
            self.files_done += 1
            self.current_file.emit(str(ev.value))
        elif ev.kind == "total":
            self.total_bytes.emit(int(ev.value))
        elif ev.kind == "error":
            self.result.errors.append(str(ev.value))
            self.error.emit(str(ev.value))
        elif ev.kind == "warning":
            self.result.warnings.append(ev.text)
        elif ev.kind == "overwrite":
            answer = self.ask_overwrite(ev.value)
            self._write(engine.OVERWRITE_ANSWERS.get(answer, "q"))
            if answer == "quit":
                self._cancelled = True
                self.result.cancelled = True
        elif ev.kind == "password":
            pw = self.ask_password()
            if pw is None:
                self.cancel()
            else:
                self._write(pw)
        elif ev.kind == "line":
            self.result.log.append(ev.text)

    def _write(self, text: str):
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.write((text + "\n").encode("utf-8"))

    def _done(self, code: int, status):
        self._read()
        for ev in self._parser.feed(self._decoder.decode(b"", final=True)) + self._parser.finish():
            self._handle(ev)
        step = self.steps[self._i]
        if self._cancelled:
            self.result.code = 255
        elif code not in step.ok_codes:
            self.result.code = max(self.result.code, code if code else 2)
            if not self.result.errors:
                self.result.errors.append(engine.EXIT_MEANING.get(code, f"7-Zip stopped with code {code}"))
        if step.on_done:
            step.on_done(code)
        self._proc = None
        if self.result.code >= 2:
            return self._finish()
        self.progress.emit(self._overall(100))
        QTimer.singleShot(0, self._next)

    def _finish(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        self.finished.emit(self.result)

    # ------------------------------------------------------------ for scripts and tests
    def run_blocking(self, timeout_ms: int = 120_000) -> Result:
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        self.finished.connect(lambda _: loop.quit())
        QTimer.singleShot(timeout_ms, loop.quit)
        self.start()
        loop.exec()
        return self.result
