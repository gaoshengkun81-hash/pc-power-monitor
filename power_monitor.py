# -*- coding: utf-8 -*-
r"""
PC Power Monitor —— 电脑总功率实时监控小桌面工具 (Windows)

数据源（按优先级自动选择，可叠加）：
  1. NVIDIA 显卡功耗   —— pynvml / nvidia-smi
  2. LibreHardwareMonitor / OpenHardwareMonitor —— WMI(root\LibreHardwareMonitor)
     需要以管理员身份运行 LHM/OHM 才能读到 CPU Package 等功耗传感器
  3. 笔记本电池放电功率 —— WMI(root\WMI BatteryStatus)
     用电池供电时，放电功率 ≈ 整机真实总功率

总功率逻辑：
  · 电池供电  -> 总功率 = 电池放电功率（最准，包含所有部件）
  · 外接电源  -> 总功率 = CPU 功耗 + GPU 功耗（能读到的部分之和）
"""
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque

# ----------------------------- 数据源层 -----------------------------

def _import_pynvml():
    try:
        import pynvml  # type: ignore
        return pynvml
    except Exception:
        return None

PYNVML = _import_pynvml()
_nvml_ok = False

def gpu_power_watts():
    """返回 (总GPU功耗W, 说明)；读不到返回 (None, 原因)"""
    global _nvml_ok
    if PYNVML is not None:
        try:
            if not _nvml_ok:
                PYNVML.nvmlInit()
                _nvml_ok = True
            total = 0.0
            for i in range(PYNVML.nvmlDeviceGetCount()):
                h = PYNVML.nvmlDeviceGetHandleByIndex(i)
                total += PYNVML.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW -> W
            return total, "NVML"
        except Exception as e:
            _nvml_ok = False
    # 退化到 nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=3,
        ).decode("gbk", "ignore")
        vals = [float(x) for x in out.replace("\r", "").split() if x.strip()]
        if vals:
            return sum(vals), "nvidia-smi"
        return None, "nvidia-smi 无数据"
    except Exception as e:
        return None, f"无NVIDIA显卡({type(e).__name__})"


def _wmi_ns(ns):
    """惰性建立 WMI 命名空间连接"""
    import wmi  # noqa
    key = "_conn_" + ns.replace("\\", "_")
    conn = globals().get(key)
    if conn is None:
        conn = wmi.WMI(namespace=ns)
        globals()[key] = conn
    return conn


def lhm_power_watts():
    """LibreHardwareMonitor / OpenHardwareMonitor -> (cpu_W, gpu_W, others_W, err)"""
    for ns in (r"root\LibreHardwareMonitor", r"root\OpenHardwareMonitor"):
        try:
            conn = _wmi_ns(ns)
            cpu = gpu = others = 0.0
            found = False
            for s in conn.Sensor():
                if s.SensorType != "Power":
                    continue
                name = (s.Name or "").lower()
                val = float(s.Value or 0)
                if "cpu package" in name:
                    cpu += val; found = True
                elif "gpu" in name and ("board" in name or "power" in name):
                    gpu += val; found = True
                elif name in ("package",):
                    cpu += val; found = True
            if found:
                return cpu, gpu, others, None
            return None, None, None, f"{ns} 运行中但没有功耗传感器"
        except Exception:
            continue
    return None, None, None, "未检测到 LHM/OHM(请以管理员运行获取CPU功耗)"


def battery_power_watts():
    """-> (放电W或None, 是否用电池)"""
    try:
        conn = _wmi_ns(r"root\WMI")
        for s in conn.BatteryStatus():
            rate = getattr(s, "DischargeRate", None)
            online = bool(getattr(s, "PowerOnline", True))
            if not online and rate:
                return float(rate) / 1000.0, True
            return None, False
    except Exception:
        pass
    try:
        import wmi  # noqa
        bats = wmi.WMI().Win32_Battery()
        if bats and all(b.BatteryStatus == 2 for b in bats):  # 2 = 在用电池
            return None, True
    except Exception:
        pass
    return None, False


def cpu_percent():
    try:
        import psutil  # noqa
        return psutil.cpu_percent(interval=None)
    except Exception:
        return None

# ----------------------------- 采集线程 -----------------------------

SAMPLE_SEC = 1.0

class Collector(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.sample = {}          # 最新一次采样
        self.history = deque(maxlen=180)  # (time, totalW)
        self._stop = False

    def run(self):
        # psutil 首次调用返回 0.0，预热
        cpu_percent()
        while not self._stop:
            t0 = time.time()
            gpu_w, gpu_src = gpu_power_watts()
            cpu_w, lhm_gpu_w, _, lhm_err = lhm_power_watts()
            bat_w, on_battery = battery_power_watts()
            if gpu_w is None and lhm_gpu_w:
                gpu_w, gpu_src = lhm_gpu_w, "LHM"
            comp = [w for w in (cpu_w, gpu_w) if w is not None]
            if on_battery and bat_w:
                total = bat_w
                mode = "电池放电(整机)"
            elif comp:
                total = sum(comp)
                mode = "部件合计"
            else:
                total = None
                mode = "无数据源"
            s = {
                "time": time.time(), "total": total, "mode": mode,
                "cpu_w": cpu_w, "gpu_w": gpu_w, "gpu_src": gpu_src,
                "bat_w": bat_w, "on_battery": on_battery,
                "cpu_pct": cpu_percent(), "lhm_err": lhm_err,
            }
            with self.lock:
                self.sample = s
                if total is not None:
                    self.history.append((s["time"], total))
            dt = SAMPLE_SEC - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def get(self):
        with self.lock:
            return dict(self.sample), list(self.history)

# ----------------------------- GUI -----------------------------

BG = "#14161a"; FG = "#e8eaf0"; DIM = "#8a8f9c"
ACCENT = "#4ade80"; WARN = "#fbbf24"; BAD = "#f87171"
FONT_BIG = ("Segoe UI", 30, "bold")
FONT_MID = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)

class App(tk.Tk):
    WIDTH, HEIGHT = 320, 400

    def __init__(self):
        super().__init__()
        self.title("功率监控")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.overrideredirect(False)

        self.collector = Collector()
        self.collector.start()

        # 右键菜单
        self.menu = tk.Menu(self, tearoff=0)
        self._topmost = tk.BooleanVar(value=True)
        self.menu.add_checkbutton(label="置顶", variable=self._topmost,
                                  command=self._toggle_top)
        self.menu.add_command(label="退出", command=self.destroy)
        self.bind("<Button-3>", lambda e: self.menu.tearoff() or self.menu.post(e.x_root, e.y_root))

        self._build()
        self._tick()

    def _toggle_top(self):
        self.attributes("-topmost", self._topmost.get())

    def _build(self):
        tk.Label(self, text="整机总功率", bg=BG, fg=DIM, font=FONT_SMALL).pack(pady=(10, 0))
        self.lbl_total = tk.Label(self, text="--.-", bg=BG, fg=FG, font=FONT_BIG)
        self.lbl_total.pack()
        self.lbl_mode = tk.Label(self, text="采集中…", bg=BG, fg=DIM, font=FONT_SMALL)
        self.lbl_mode.pack()

        # 历史曲线
        self.canvas = tk.Canvas(self, width=self.WIDTH - 20, height=90,
                                bg=BG, highlightthickness=1,
                                highlightbackground="##2a2e36".replace("##", "#"))
        self.canvas.pack(pady=8)

        # 分项
        rows = tk.Frame(self, bg=BG)
        rows.pack(fill="x", padx=18)
        self.lbl_cpu = self._row(rows, "CPU 功耗", 0)
        self.lbl_gpu = self._row(rows, "GPU 功耗", 1)
        self.lbl_bat = self._row(rows, "电池放电", 2)
        self.lbl_util = self._row(rows, "CPU 占用", 3)

        self.lbl_hint = tk.Label(self, text="", bg=BG, fg=WARN, font=FONT_SMALL, wraplength=self.WIDTH - 30)
        self.lbl_hint.pack(side="bottom", pady=6)

    def _row(self, parent, name, r):
        tk.Label(parent, text=name, bg=BG, fg=DIM, font=FONT_SMALL,
                 anchor="w", width=10).grid(row=r, column=0, sticky="w")
        lbl = tk.Label(parent, text="--", bg=BG, fg=FG, font=FONT_MID,
                       anchor="e", width=10)
        lbl.grid(row=r, column=1, sticky="e")
        return lbl

    @staticmethod
    def _fmt(v, unit="W"):
        return "--" if v is None else f"{v:,.1f} {unit}"

    def _draw_spark(self, history):
        c = self.canvas
        c.delete("all")
        w = int(c["width"]); h = int(c["height"])
        if len(history) < 2:
            c.create_text(w // 2, h // 2, text="等待数据…", fill=DIM, font=FONT_SMALL)
            return
        vals = [v for _, v in history]
        vmax = max(max(vals) * 1.15, 10)
        step = w / (self.canvas_max - 1)
        pts = []
        for i, (_, v) in enumerate(history):
            x = w - (len(history) - 1 - i) * step
            y = h - 4 - (v / vmax) * (h - 12)
            pts += [x, y]
        c.create_line(*pts, fill=ACCENT, width=2, smooth=True)
        c.create_text(4, 6, text=f"峰值 {max(vals):,.0f} W", fill=DIM,
                      font=FONT_SMALL, anchor="nw")

    canvas_max = 180  # history maxlen

    def _tick(self):
        s, history = self.collector.get()
        if not s:
            self.after(500, self._tick)
            return
        total = s["total"]
        if total is None:
            self.lbl_total.config(text="--.-", fg=DIM)
            self.lbl_mode.config(text="未找到数据源")
            self.lbl_hint.config(
                text="提示: 以管理员身份运行 LibreHardwareMonitor 可读取 CPU 等功耗; "
                     "NVIDIA 显卡可自动读取 GPU 功耗; 笔记本用电池时显示真实整机功率")
        else:
            color = ACCENT if total < 150 else (WARN if total < 300 else BAD)
            self.lbl_total.config(text=f"{total:,.1f}", fg=color)
            self.lbl_mode.config(text=f"W · {s['mode']}")
            self.lbl_hint.config(text="")
        self.lbl_cpu.config(text=self._fmt(s["cpu_w"]))
        self.lbl_gpu.config(text=self._fmt(s["gpu_w"]))
        self.lbl_bat.config(text=self._fmt(s["bat_w"]))
        self.lbl_util.config(text=self._fmt(s["cpu_pct"], "%"))
        self._draw_spark(history)
        self.after(500, self._tick)

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("按回车退出...")
        sys.exit(1)
