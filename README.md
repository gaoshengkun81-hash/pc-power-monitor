# PC Power Monitor —— 电脑总功率实时监控小桌面工具

一个常驻桌面的小窗口，每秒刷新一次整机功耗，带 3 分钟历史曲线和分项明细。

![平台](https://img.shields.io/badge/平台-Windows-blue) ![依赖](https://img.shields.io/badge/依赖-Python%203.9%2B-green)

## 界面

- 大号字体实时显示**整机总功率 (W)**，按负载变色（绿 < 150W < 黄 < 300W < 红）
- 历史功率曲线（180 秒）+ 峰值标注
- 分项：CPU 功耗 / GPU 功耗 / 电池放电 / CPU 占用率
- 右键菜单：置顶开关、退出

## 安装与运行

```bat
pip install -r requirements.txt
python power_monitor.py
```

或直接双击 `启动.bat`。

## 数据源说明（自动探测，无需配置）

| 数据源 | 能读到什么 | 前提 |
|---|---|---|
| NVIDIA NVML / nvidia-smi | GPU 实时功耗 | 装有 N 卡驱动 |
| LibreHardwareMonitor (LHM) | CPU Package 等全部传感器功耗 | 以**管理员身份**运行 LHM（免费开源，会自动建立 `root\LibreHardwareMonitor` WMI 命名空间） |
| OpenHardwareMonitor | 同上（备选） | 以管理员身份运行 |
| 电池放电功率 (`root\WMI`) | 用电池时 ≈ **真实整机总功率** | 笔记本 |

**总功率计算逻辑：**

- 用电池供电 → 总功率 = 电池放电功率（包含所有部件，最准确）
- 外接电源 → 总功率 = CPU 功耗 + GPU 功耗（能读到的部分之和）

> 台式机想看到 CPU 功耗，推荐配合 [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) 使用：管理员启动 LHM 后保持后台运行，本工具自动读取。

## 文件结构

```
pc-power-monitor/
├── power_monitor.py   # 主程序（单文件，含数据源 + 采集线程 + Tkinter 界面）
├── requirements.txt
├── 启动.bat
└── README.md
```

## 常见问题

- **显示 `--` / 无数据源**：台式机没有电池、没有 N 卡时，必须配合 LHM/OHM 运行（管理员）才能读到功耗。
- **GPU 功耗为 `--`**：确认显卡为 NVIDIA；AMD/Intel 显卡请依赖 LHM 读取。
- **想开机自启**：为 `启动.bat` 创建快捷方式放到 `shell:startup` 文件夹。
