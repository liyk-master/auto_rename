"""
Video Organizer - Windows 桌面版启动器

双击运行，自动打开浏览器，支持托盘图标管理。
支持首次运行配置对话框（端口+模式选择）。
"""

import sys
import os
import configparser
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk
from pathlib import Path


def _get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


CONFIG_FILE = _get_app_dir() / "launcher.ini"
APP_DIR = _get_app_dir()
SRC_DIR = APP_DIR / "src"


def _ensure_src_path():
    src = str(SRC_DIR.resolve())
    if src not in sys.path:
        sys.path.insert(0, src)


MODE_DISPLAY = {
    "web-only": "仅 Web 管理后台",
    "web": "Web + 文件监控",
    "monitor": "仅文件监控",
}


def load_config() -> dict:
    cp = configparser.ConfigParser()
    cp.read(str(CONFIG_FILE))
    return {
        "port": cp.get("general", "port", fallback="8080"),
        "mode": cp.get("general", "mode", fallback="web-only"),
    }


def save_config(port: str, mode: str):
    cp = configparser.ConfigParser()
    cp["general"] = {"port": str(port), "mode": mode}
    with open(str(CONFIG_FILE), "w", encoding="utf-8") as f:
        cp.write(f)


def show_config_dialog() -> tuple:
    root = tk.Tk()
    root.title("Video Organizer 启动配置")
    root.geometry("420x280")
    root.resizable(False, False)
    root.update_idletasks()
    x = (root.winfo_screenwidth() - 420) // 2
    y = (root.winfo_screenheight() - 280) // 2
    root.geometry(f"+{x}+{y}")

    result = {"port": "8080", "mode": "web-only"}
    mode_reverse = {v: k for k, v in MODE_DISPLAY.items()}

    tk.Label(root, text="Video Organizer", font=("微软雅黑", 16, "bold")).pack(pady=(20, 5))
    tk.Label(root, text="请选择启动模式和端口", font=("微软雅黑", 10)).pack(pady=(0, 20))

    frame = tk.Frame(root)
    frame.pack(pady=10)

    tk.Label(frame, text="端口:", font=("微软雅黑", 10)).grid(row=0, column=0, padx=5, pady=5, sticky="e")
    port_var = tk.StringVar(value="8080")
    port_entry = tk.Entry(frame, textvariable=port_var, width=10, font=("微软雅黑", 10))
    port_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

    tk.Label(frame, text="模式:", font=("微软雅黑", 10)).grid(row=1, column=0, padx=5, pady=5, sticky="e")
    mode_var = tk.StringVar(value=MODE_DISPLAY["web-only"])
    mode_combo = ttk.Combobox(frame, textvariable=mode_var, values=list(MODE_DISPLAY.values()), state="readonly", width=22, font=("微软雅黑", 10))
    mode_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")

    def on_mode_change(event=None):
        selected = mode_var.get()
        key = mode_reverse.get(selected)
        if key == "monitor":
            port_entry.config(state="disabled")
        else:
            port_entry.config(state="normal")

    mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

    def on_start():
        result["port"] = port_var.get().strip()
        result["mode"] = mode_reverse.get(mode_var.get(), "web-only")
        root.destroy()

    tk.Button(root, text="保存并启动", command=on_start, font=("微软雅黑", 10), width=15, bg="#4CAF50", fg="white").pack(pady=20)

    root.mainloop()
    return result["port"], result["mode"]


def start_server(port: int):
    _ensure_src_path()
    try:
        from src.video_organizer.web.app import create_app
        import uvicorn
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        import traceback
        with open(APP_DIR / "launcher_error.log", "w", encoding="utf-8") as f:
            f.write(f"启动失败: {e}\n{traceback.format_exc()}")
        raise


def start_monitor():
    _ensure_src_path()
    try:
        from src.video_organizer.core.config_loader import load_config as load_app_config
        from src.video_organizer.main import initialize_monitor
        from src.video_organizer.web.services.state import get_state_manager

        config = load_app_config()
        state = get_state_manager()
        if not state.get_config():
            state.set_config(config, None)
        state.set_system_running(True)

        monitor = initialize_monitor(config)
        if monitor:
            monitor.start()
    except Exception as e:
        import traceback
        with open(APP_DIR / "launcher_error.log", "w", encoding="utf-8") as f:
            f.write(f"监控启动失败: {e}\n{traceback.format_exc()}")
        raise


def main():
    config = load_config()

    if not CONFIG_FILE.exists():
        port, mode = show_config_dialog()
        save_config(port, mode)
    else:
        port = config["port"]
        mode = config["mode"]

    port = int(port) if mode != "monitor" else 0

    if mode in ("web-only", "web"):
        t = threading.Thread(target=start_server, args=(port,), daemon=True)
        t.start()

    if mode in ("web", "monitor"):
        t = threading.Thread(target=start_monitor, daemon=True)
        t.start()

    if mode in ("web-only", "web"):
        def _open_browser():
            time.sleep(2)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    import pystray
    from PIL import Image, ImageDraw, ImageFont

    icon_size = 64
    img = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=(73, 109, 137))
    draw.rounded_rectangle([10, 10, 54, 54], radius=8, fill=(255, 255, 255, 30))
    draw.text((20, 18), "VO", fill=(255, 255, 255), font=None)

    def open_browser_action(icon, item):
        if mode in ("web-only", "web"):
            webbrowser.open(f"http://localhost:{port}")

    def edit_config_action(icon, item):
        if not CONFIG_FILE.exists():
            save_config(str(port), mode)
        os.startfile(str(CONFIG_FILE))

    def exit_action(icon, item):
        icon.stop()
        os._exit(0)

    display_name = MODE_DISPLAY.get(mode, mode)
    menu = pystray.Menu(
        pystray.MenuItem(f"打开浏览器 (:{port})", open_browser_action, enabled=lambda _: mode != "monitor"),
        pystray.MenuItem("编辑配置文件", edit_config_action),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", exit_action),
    )

    icon = pystray.Icon("video_organizer", img, f"Video Organizer - {display_name}", menu)
    icon.run()


if __name__ == "__main__":
    main()
