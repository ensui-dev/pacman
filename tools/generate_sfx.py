"""Generate an original retro SFX set mirroring ``assets/sfx/``.

Synthesizes chiptune-style stand-ins for every file in the classic kit,
same filenames, similar durations, different (original) sounds into
``assets/sfx_generated/``. Swapping the directories is then a zero-code
change for the audio wiring.

Pure numpy + stdlib ``wave``; 48 kHz mono 16-bit like the originals.
"""
from __future__ import annotations

import os
import wave
from collections.abc import Sequence

import numpy as np

SR = 48_000
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "sfx_generated")

# 12-TET note frequencies, A4 = 440 Hz. "C5" etc.; "." is a rest.
_NOTE_OFFSETS = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def _freq(name: str) -> float:
    """Frequency in Hz for a note name like ``C5`` or ``F#4``."""
    letter, rest = name[0], name[1:]
    sharp = rest.startswith("#")
    octave = int(rest[1:] if sharp else rest)
    semis = _NOTE_OFFSETS[letter] + (1 if sharp else 0) + 12 * (octave - 4)
    return 440.0 * 2 ** (semis / 12)


def _osc(freqs: np.ndarray, shape: str) -> np.ndarray:
    """Oscillator with sample-wise frequency (continuous phase, no clicks)."""
    phase = 2 * np.pi * np.cumsum(freqs) / SR
    if shape == "square":
        return np.sign(np.sin(phase))
    if shape == "triangle":
        return (2 / np.pi) * np.arcsin(np.sin(phase))
    return np.sin(phase)


def _env(n: int, attack: float = 0.005, release: float = 0.01) -> np.ndarray:
    """Linear attack/release envelope; keeps every sound click-free."""
    out = np.ones(n)
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    a, r = min(a, n), min(r, n)
    out[:a] = np.linspace(0.0, 1.0, a)
    out[-r:] *= np.linspace(1.0, 0.0, r)
    return out


def _chirp(f0: float, f1: float, dur: float, shape: str = "square",
           vol: float = 0.5, curve: float = 1.0) -> np.ndarray:
    """A frequency sweep from ``f0`` to ``f1`` over ``dur`` seconds."""
    n = int(dur * SR)
    t = np.linspace(0.0, 1.0, n) ** curve
    out: np.ndarray = _osc(f0 + (f1 - f0) * t, shape) * _env(n) * vol
    return out


def _tone(freq: float, dur: float, shape: str = "square",
          vol: float = 0.5, vib_hz: float = 0.0,
          vib_depth: float = 0.0) -> np.ndarray:
    """A steady tone, with optional vibrato."""
    n = int(dur * SR)
    f = np.full(n, freq)
    if vib_hz:
        t = np.arange(n) / SR
        f = f * (1 + vib_depth * np.sin(2 * np.pi * vib_hz * t))
    out: np.ndarray = _osc(f, shape) * _env(n) * vol
    return out


def _silence(dur: float) -> np.ndarray:
    """Plain silence."""
    return np.zeros(int(dur * SR))


def _melody(notes: Sequence[tuple[str, float]], step: float,
            shape: str = "square", vol: float = 0.4) -> np.ndarray:
    """Render ``(note, beats)`` pairs at ``step`` seconds per beat."""
    parts = []
    for name, beats in notes:
        dur = beats * step
        if name == ".":
            parts.append(_silence(dur))
        else:
            parts.append(_tone(_freq(name), dur * 0.92, shape, vol)
                         if dur > 0.05 else
                         _tone(_freq(name), dur, shape, vol))
            if dur > 0.05:
                parts.append(_silence(dur * 0.08))
    return np.concatenate(parts)


def _mix(*tracks: np.ndarray) -> np.ndarray:
    """Sum tracks (padded to the longest), then soft-limit the peak."""
    n = max(len(t) for t in tracks)
    out = np.zeros(n)
    for t in tracks:
        out[:len(t)] += t
    peak = np.max(np.abs(out))
    return out / peak * 0.6 if peak > 0.6 else out


def _write(name: str, samples: np.ndarray) -> None:
    """Write 16-bit mono WAV into the output directory."""
    path = os.path.join(OUT_DIR, name)
    data = np.clip(samples, -1.0, 1.0)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((data * 32767).astype("<i2").tobytes())
    print(f"  {name:28s} {len(samples) / SR:5.2f}s")


# The set
def build_all() -> None:
    """Synthesize every file of the kit."""
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"writing to {OUT_DIR}")

    # waka: alternating down/up blips (the pair makes the chomp rhythm)
    _write("eat_dot_0.wav", _chirp(640, 320, 0.08, "square", 0.45))
    _write("eat_dot_1.wav", _chirp(320, 640, 0.08, "square", 0.45))

    # fruit: quick rising major arpeggio
    _write("eat_fruit.wav", np.concatenate([
        _tone(_freq(n), 0.095, "triangle", 0.5)
        for n in ("C5", "E5", "G5", "C6")]))

    # ghost eaten: long upward zip with vibrato tail
    _write("eat_ghost.wav", np.concatenate([
        _chirp(180, 1100, 0.38, "square", 0.5, curve=0.6),
        _tone(1100, 0.14, "square", 0.4, vib_hz=28, vib_depth=0.04)]))

    # extra life: sparkling two-octave arpeggio, repeated
    arp = [("C5", 1), ("E5", 1), ("G5", 1), ("C6", 1),
           ("E6", 1), ("G6", 1), ("C7", 2)]
    _write("extend.wav", _melody(arp * 2 + [(".", 2)], 0.115,
                                 "triangle", 0.5))

    # coin blip: two quick fifths
    _write("credit.wav", np.concatenate([
        _tone(_freq("A5"), 0.09, "square", 0.5),
        _tone(_freq("E6"), 0.12, "square", 0.5)]))

    # death: long wobbling fall, then two low plops
    n = int(2.7 * SR)
    t = np.linspace(0.0, 1.0, n)
    fall = 850 * (1 - t) ** 1.6 + 70
    wob = fall * (1 + 0.06 * np.sin(2 * np.pi * (6 + 10 * t) * t * SR / SR))
    _write("death_0.wav", np.concatenate([
        _osc(wob, "square") * _env(n, 0.01, 0.15) * 0.5,
        _silence(0.25)]))
    _write("death_1.wav", np.concatenate([
        _chirp(160, 60, 0.09, "square", 0.55),
        _silence(0.02),
        _chirp(160, 60, 0.09, "square", 0.55)]))

    # sirens: one smooth up-down cycle per file; higher + faster per tier.
    # Cycles start/end at the low point so the main files loop cleanly.
    for i, (lo, hi, cyc) in enumerate([
            (320, 520, 0.399), (380, 610, 0.365), (440, 700, 0.331),
            (500, 800, 0.296), (560, 900, 0.264)]):
        half = cyc / 2
        up = _chirp(lo, hi, half, "triangle", 0.4)
        down = _chirp(hi, lo, half, "triangle", 0.4)
        _write(f"siren{i}.wav", np.concatenate([up, down]))
        _write(f"siren{i}_firstloop.wav",
               _chirp(lo * 0.6, lo, cyc * 0.95, "triangle", 0.4, curve=0.7))

    # frightened: bubbling rising chirps (6 per loop), low and wobbly
    blip = _chirp(140, 380, 0.176, "square", 0.38, curve=0.8)
    _write("fright.wav", np.concatenate([blip] * 6))
    _write("fright_firstloop.wav", _chirp(90, 140, 0.115, "square", 0.38))

    # eyes home: fast high falling ping-pong
    ping = _chirp(1500, 950, 0.132, "triangle", 0.35)
    _write("eyes.wav", np.concatenate([ping, ping]))
    _write("eyes_firstloop.wav", _chirp(1800, 1500, 0.247, "triangle", 0.35))

    # start jingle (~4.2s): original riff, lead + simple bass
    step = 0.131
    lead = [("C5", 1), ("G4", 1), ("E5", 1), ("G4", 1),
            ("C6", 1), ("G5", 1), ("E5", 1), ("C5", 1),
            ("D5", 1), ("A4", 1), ("F5", 1), ("A4", 1),
            ("D6", 1), ("A5", 1), ("F5", 1), ("D5", 1),
            ("E5", 1), ("B4", 1), ("G5", 1), ("B4", 1),
            ("E6", 1), ("B5", 1), ("G5", 1), ("E5", 1),
            ("C6", 1), ("E6", 1), ("G6", 1), ("C7", 3), (".", 2)]
    bass = [("C3", 4), ("C3", 4), ("D3", 4), ("D3", 4),
            ("E3", 4), ("E3", 4), ("C3", 4), ("C3", 2), (".", 2)]
    _write("start.wav", _mix(_melody(lead, step, "square", 0.42),
                             _melody(bass, step, "triangle", 0.3)))

    # intermission (~5.3s): bouncy victory loop
    step = 0.12
    lead = [("F5", 1), ("A5", 1), ("C6", 2), ("A5", 1), ("F5", 1),
            ("G5", 2), ("E5", 1), ("G5", 1), ("B5", 2), ("G5", 1),
            ("E5", 1), ("F5", 2), ("A5", 1), ("C6", 1), ("F6", 2),
            ("C6", 1), ("A5", 1), ("C6", 4), (".", 1),
            ("F5", 1), ("A5", 1), ("C6", 2), ("D6", 1), ("C6", 1),
            ("A5", 2), ("F5", 1), ("G5", 1), ("A5", 4), (".", 2)]
    bass = [("F3", 4), ("C3", 4), ("E3", 4), ("C3", 4), ("F3", 4),
            ("F3", 4), ("F3", 4), ("F3", 4), ("D3", 4), ("C3", 6)]
    _write("intermission.wav", _mix(_melody(lead, step, "square", 0.42),
                                    _melody(bass, step, "triangle", 0.3)))


if __name__ == "__main__":
    build_all()
