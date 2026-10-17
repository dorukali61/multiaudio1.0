"""Ses motoru: Windows WASAPI loopback ile sistem sesini yakalar, secilen ek cikislara dagitir."""
import collections
import threading
import time

import numpy as np
import pyaudiowpatch as pa


def list_outputs(p):
    """(cikis cihazlari, varsayilan cikis cihazinin index'i) dondurur."""
    wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
    outs = []
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d["hostApi"] != wasapi["index"]:
            continue
        if d["maxOutputChannels"] < 1 or d.get("isLoopbackDevice"):
            continue
        if "hands-free" in d["name"].lower():  # Bluetooth mono telefon profili, muzik icin uygun degil
            continue
        outs.append(d)
    return outs, wasapi["defaultOutputDevice"]


class Sink(threading.Thread):
    """Tek bir cikis cihazina ses yazar. params: {'delay': ms, 'gain': 0..1} (canli degistirilebilir)."""

    def __init__(self, p, dev, params):
        super().__init__(daemon=True)
        self.params = params
        self.rate = int(dev["defaultSampleRate"])
        self.ch = 2 if dev["maxOutputChannels"] >= 2 else 1
        self.q = collections.deque(maxlen=600)
        self.running = True
        self.stream = p.open(
            format=pa.paInt16, channels=self.ch, rate=self.rate, output=True,
            output_device_index=dev["index"], frames_per_buffer=self.rate // 100,
        )

    def push(self, t, x, src_rate):
        """x: float32 (n, 2). Hedef hiza gore yeniden ornekler, ses seviyesini uygular."""
        n = len(x)
        if src_rate != self.rate:
            m = max(1, round(n * self.rate / src_rate))
            idx = np.linspace(0, n - 1, m)
            grid = np.arange(n)
            x = np.stack([np.interp(idx, grid, x[:, 0]), np.interp(idx, grid, x[:, 1])], axis=1)
        x = x * float(self.params["gain"])
        if self.ch == 1:
            x = x.mean(axis=1, keepdims=True)
        pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        self.q.append((t, pcm))

    def run(self):
        silence = bytes((self.rate // 200) * self.ch * 2)  # 5 ms sessizlik
        try:
            while self.running:
                now = time.monotonic()
                delay = float(self.params["delay"]) / 1000.0
                while self.q and self.q[0][0] + delay < now - 0.03:  # cok gecikmis parcalari at
                    self.q.popleft()
                if self.q and self.q[0][0] + delay <= now:
                    self.stream.write(self.q.popleft()[1])
                else:
                    self.stream.write(silence)
        except Exception:
            pass
        finally:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass


class Mirror:
    def __init__(self, p):
        self.p = p
        self.cap = None
        self.sinks = []
        self.running = False
        self.cap_ch = 2
        self.cap_rate = 48000

    def find_loopback(self, out):
        for lb in self.p.get_loopback_device_info_generator():
            if out["name"] in lb["name"]:
                return lb
        return None

    def start(self, source, targets):
        """source: kaynak cikis cihazi (sesi zaten orada caliyor). targets: [(cihaz, params), ...]"""
        lb = self.find_loopback(source)
        if lb is None:
            raise RuntimeError("Kaynak cihaz icin loopback bulunamadi.")
        self.cap_ch = int(lb["maxInputChannels"])
        self.cap_rate = int(lb["defaultSampleRate"])
        self.sinks = [Sink(self.p, d, prm) for d, prm in targets]
        for s in self.sinks:
            s.start()
        self.cap = self.p.open(
            format=pa.paInt16, channels=self.cap_ch, rate=self.cap_rate,
            frames_per_buffer=self.cap_rate // 100, input=True,
            input_device_index=lb["index"], stream_callback=self._on_audio,
        )
        self.running = True

    def _on_audio(self, data, frames, tinfo, status):
        t = time.monotonic()
        x = np.frombuffer(data, dtype=np.int16).reshape(-1, self.cap_ch).astype(np.float32) / 32768.0
        if self.cap_ch == 1:
            x = np.repeat(x, 2, axis=1)
        elif self.cap_ch > 2:
            x = x[:, :2]
        for s in self.sinks:
            s.push(t, x, self.cap_rate)
        return (data, pa.paContinue)

    def stop(self):
        self.running = False
        if self.cap is not None:
            try:
                self.cap.stop_stream()
                self.cap.close()
            except Exception:
                pass
            self.cap = None
        for s in self.sinks:
            s.running = False
        for s in self.sinks:
            s.join(timeout=1.0)
        self.sinks = []
