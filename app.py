import tkinter as tk
from tkinter import messagebox, ttk

import pyaudiowpatch as pa

from engine import Mirror, list_outputs


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Multi Audio")
        self.geometry("500x600")
        self.p = pa.PyAudio()
        self.mirror = Mirror(self.p)
        self.outs = []
        self.rows = []
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        ttk.Label(
            self, wraplength=470,
            text="Kaynak cihaz: sesin zaten çaldığı cihaz (Windows'ta varsayılan çıkış). "
                 "O cihaz kendi başına çalmaya devam eder; aşağıdan sadece EKSTRA cihazları işaretle.",
        ).pack(anchor="w", padx=12, pady=(12, 4))
        self.src = ttk.Combobox(self, state="readonly")
        self.src.pack(fill="x", padx=12)
        self.src.bind("<<ComboboxSelected>>", lambda e: self.build_rows())

        ttk.Label(self, text="Ekstra çıkışlar:").pack(anchor="w", padx=12, pady=(12, 2))
        self.box = ttk.Frame(self)
        self.box.pack(fill="both", expand=True, padx=12)

        bar = ttk.Frame(self)
        bar.pack(pady=8)
        ttk.Button(bar, text="Yenile", command=self.refresh).pack(side="left", padx=4)
        self.btn = ttk.Button(bar, text="Başlat", command=self.toggle)
        self.btn.pack(side="left", padx=4)
        self.status = ttk.Label(self, text="", wraplength=470)
        self.status.pack(padx=12, pady=(0, 10))
        self.refresh()

    def refresh(self):
        if self.mirror.running:
            return
        self.p.terminate()  # yeni takilan cihazlarin gorunmesi icin PortAudio'yu yeniden baslat
        self.p = pa.PyAudio()
        self.mirror.p = self.p
        self.outs, default_idx = list_outputs(self.p)
        self.src["values"] = [d["name"] for d in self.outs]
        if self.outs:
            self.src.current(next((i for i, d in enumerate(self.outs) if d["index"] == default_idx), 0))
        self.build_rows()

    def build_rows(self):
        for w in self.box.winfo_children():
            w.destroy()
        self.rows = []
        if not self.outs:
            self.status.config(text="Çıkış cihazı bulunamadı. Bluetooth cihazlarını Windows'ta bağla, sonra Yenile'ye bas.")
            return
        src = self.outs[self.src.current()]
        for d in self.outs:
            if d["index"] == src["index"]:
                continue  # kaynak cihaza geri besleme olmasin
            params = {"delay": 0.0, "gain": 1.0}
            use = tk.BooleanVar()
            f = ttk.LabelFrame(self.box)
            f.pack(fill="x", pady=3)
            ttk.Checkbutton(f, text=d["name"], variable=use).pack(anchor="w")
            row = ttk.Frame(f)
            row.pack(fill="x")
            ttk.Label(row, text="Gecikme (ms)").grid(row=0, column=0, sticky="w", padx=4)
            tk.Scale(row, from_=0, to=1000, resolution=5, orient="horizontal", length=300,
                     command=lambda v, p=params: p.__setitem__("delay", float(v))).grid(row=0, column=1)
            ttk.Label(row, text="Ses (%)").grid(row=1, column=0, sticky="w", padx=4)
            vol = tk.Scale(row, from_=0, to=100, orient="horizontal", length=300,
                           command=lambda v, p=params: p.__setitem__("gain", float(v) / 100.0))
            vol.set(100)
            vol.grid(row=1, column=1)
            self.rows.append((d, use, params))

    def toggle(self):
        if self.mirror.running:
            self.mirror.stop()
            self.btn.config(text="Başlat")
            self.status.config(text="Durduruldu.")
            return
        chosen = [(d, prm) for d, use, prm in self.rows if use.get()]
        if not chosen:
            self.status.config(text="En az bir ekstra çıkış işaretle.")
            return
        src = self.outs[self.src.current()]
        try:
            self.mirror.start(src, chosen)
        except Exception as e:
            self.mirror.stop()
            messagebox.showerror("Hata", f"Başlatılamadı:\n{e}")
            return
        self.btn.config(text="Durdur")
        self.status.config(
            text=f"{len(chosen)} cihaza yansıtılıyor. Gecikme ve ses ayarları canlı değişir. "
                 "Yankı duyarsan hızlı olan cihazın gecikmesini artır."
        )

    def on_close(self):
        self.mirror.stop()
        self.p.terminate()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
