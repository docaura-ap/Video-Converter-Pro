import sys
import os

def resource_path(rel=""):
    """Resolve a path relative to the project root (dev) or PyInstaller bundle."""
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel) if rel else base


def run_webview():
    import webview
    from backend.api import Api

    api = Api()
    win = webview.create_window(
        title="Video Converter Pro",
        url=resource_path(os.path.join("frontend", "index.html")),
        js_api=api,
        width=1320,
        height=856,
        min_size=(960, 640),
        frameless=True,
        easy_drag=False,
        background_color="#f5f2ee",
    )
    api.set_window(win)
    webview.start(debug="--debug" in sys.argv, private_mode=True)


if __name__ == "__main__":
    try:
        run_webview()
    except Exception as e:
        import traceback

        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "startup_error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)

        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Video Converter Pro — Startup Error",
                f"{e}\n\nFull details saved to:\n{log_path}"
            )
            root.destroy()
        except Exception:
            pass
