"""Acoustic run/turn markers distinguish owned speech from tones and ambient sound."""

import hashlib
import math
import struct

FREQUENCIES = (900, 1500, 2100, 2700, 3300)


def marker_symbols(run_id, turn):
    digest = hashlib.sha256(f"{run_id}:{turn}".encode()).digest()
    digits = []
    previous = None
    for byte in digest[:8]:
        choices = [digit for digit in range(4) if digit != previous]
        previous = choices[byte % len(choices)]
        digits.append(previous)
    return [symbol for digit in digits for symbol in (4, digit)] + [4]


def marker_pcm(run_id, turn, sample_rate=48000):
    samples = []
    for symbol in marker_symbols(run_id, turn):
        frequency = FREQUENCIES[symbol]
        count = int(sample_rate * 0.3)
        samples.extend(round(12000 * math.sin(2 * math.pi * frequency * n / sample_rate)) for n in range(count))
        samples.extend([0] * int(sample_rate * 0.04))
    return struct.pack(f"<{len(samples)}h", *samples)


class AcousticSource:
    def __init__(self, run_id):
        self.run_id = run_id
        self.turn = 1
        self.last = None
        self.duration = 0
        self.recorded = False
        self.symbols = []
        self.receipts = []
        self.observed_symbols = []
        self.max_purity = 0.0
        self.sample_rates = set()
        self.pending = []
        self.frames = 0
        self.last_peak = 0

    def observe(self, samples, sample_rate):
        self.frames += 1
        self.last_peak = max(map(abs, samples), default=0)
        self.sample_rates.add(sample_rate)
        if len(self.sample_rates) != 1:
            raise RuntimeError("acoustic source sample rate changed")
        self.pending.extend(samples)
        size = sample_rate // 50
        result = None
        while len(self.pending) >= size:
            window, self.pending = self.pending[:size], self.pending[size:]
            receipt = self._observe_window(window, sample_rate)
            if receipt is not None:
                if result is not None:
                    raise RuntimeError("multiple acoustic turns in one input frame")
                result = receipt
        return result

    def _observe_window(self, samples, sample_rate):
        count = len(samples)
        energy = sum(sample * sample for sample in samples)
        symbol = None
        if count and max(map(abs, samples)) >= 500 and energy:
            strengths = []
            for frequency in FREQUENCIES:
                coefficient = 2 * math.cos(2 * math.pi * frequency / sample_rate)
                previous = prior = 0
                for sample in samples:
                    current = sample + coefficient * previous - prior
                    prior, previous = previous, current
                strengths.append(previous * previous + prior * prior - coefficient * previous * prior)
            peak = max(strengths)
            purity = 2 * peak / (count * energy)
            self.max_purity = max(self.max_purity, purity)
            if purity >= 0.65:
                symbol = strengths.index(peak)
        if symbol != self.last:
            self.last, self.duration, self.recorded = symbol, 0, False
        self.duration += count / sample_rate
        if symbol is None or self.recorded or self.duration < 0.08:
            return None
        self.recorded = True
        if self.symbols and self.symbols[-1] == symbol:
            return None
        self.observed_symbols.append(symbol)
        self.symbols = [*self.symbols, symbol][-17:]
        if self.symbols != marker_symbols(self.run_id, self.turn):
            return None
        receipt = {"run_id": self.run_id, "turn": self.turn, "source": "owned-acoustic-marker"}
        self.receipts.append(receipt)
        self.turn += 1
        self.symbols = []
        return receipt
