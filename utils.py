import logging
import sys
import os
import subprocess
import shutil
import json
import threading
import tempfile
from datetime import datetime

# Serialises all read-modify-write cycles on history.json so concurrent
# completions from parallel workers don't clobber each other's entries.
_history_lock = threading.Lock()

# Windows legacy MAX_PATH limit (applies when long-path support is not enabled).
_WIN_MAX_PATH = 260

def _get_base_path():
    """Returns the base path for resources/logs."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def setup_logging():
    """Configures logging for the application."""
    log_dir = os.path.join(_get_base_path(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"converter_{timestamp}.log")
    
    logger = logging.getLogger("VideoConverter")
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if called more than once
    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(levelname)s: %(message)s')

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

def open_logs_folder():
    """Opens the logs folder in Explorer."""
    log_dir = os.path.join(_get_base_path(), "logs")
    if os.path.exists(log_dir):
        os.startfile(log_dir)

def format_duration(seconds):
    """Formats seconds into HH:MM:SS."""
    if not isinstance(seconds, (int, float)):
        return "00:00:00"
    
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def detect_hardware_encoders():
    """Detects available hardware encoders in FFmpeg."""
    # standalone binary resolution to avoid circular imports
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    ffmpeg_cmd = os.path.join(base_path, 'bin', 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_cmd):
        ffmpeg_cmd = 'ffmpeg.exe'
        
    encoders = {
        'NVIDIA (NVENC)': False,
        'Intel (QSV)': False,
        'AMD (AMF)': False
    }
    
    try:
        cmd = [ffmpeg_cmd, '-encoders']
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        output = result.stdout
        
        # Check standard h264 capability
        if 'h264_nvenc' in output:
            encoders['NVIDIA (NVENC)'] = True
        if 'h264_qsv' in output:
            encoders['Intel (QSV)'] = True
        if 'h264_amf' in output:
            encoders['AMD (AMF)'] = True
    except Exception as e:
        print(f"Error detecting hardware encoders: {e}")
        
    return encoders

def _truncate_for_max_path(output_dir, base_name, extension, suffix=""):
    """
    Return a base_name that, when combined with output_dir / suffix . extension,
    stays within the Windows MAX_PATH limit (260 chars).  No-op on non-Windows.
    """
    if os.name != 'nt':
        return base_name
    # Reserve 1 for separator, len(suffix) for counter, 1 for '.', len(ext)
    overhead = len(output_dir) + 1 + len(suffix) + 1 + len(extension)
    allowed = _WIN_MAX_PATH - overhead
    if allowed < 1:
        return 'converted'  # extreme edge case — dir itself is too long
    return base_name[:allowed]


def get_unique_output_path(output_dir, filename, extension, reserved=None):
    """Generates a unique output path to avoid overwriting.

    `reserved` is an optional set of paths already assigned in the current
    batch (in-memory reservation).  Without it, parallel same-base-name files
    all resolve to the same path before any output file exists on disk.
    """
    base_name = os.path.splitext(filename)[0]
    safe_base = _truncate_for_max_path(output_dir, base_name, extension)
    output_path = os.path.join(output_dir, f"{safe_base}.{extension}")

    counter = 1
    while os.path.exists(output_path) or (reserved is not None and output_path in reserved):
        suffix = f"_{counter}"
        safe_base = _truncate_for_max_path(output_dir, base_name, extension, suffix)
        output_path = os.path.join(output_dir, f"{safe_base}{suffix}.{extension}")
        counter += 1

    return output_path

def get_file_size(path):
    """Returns human-readable file size."""
    try:
        # Check if path is integer (bytes) instead of file path
        if isinstance(path, (int, float)):
            size = path
        else:
            size = os.path.getsize(path)
            
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    except Exception:
        return "Unknown"

def get_history_file_path():
    """Returns the persistent path to local history.json."""
    appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    history_dir = os.path.join(appdata, 'VideoConverterPro')
    os.makedirs(history_dir, exist_ok=True)
    return os.path.join(history_dir, 'history.json')

def append_history(input_name, output_format, file_size, duration, status):
    """Appends a new conversion entry to history.json (thread-safe, atomic write)."""
    path = get_history_file_path()
    record = {
        'input_name': input_name,
        'output_format': output_format,
        'file_size': file_size,
        'duration': duration,
        'status': status,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with _history_lock:
        try:
            records = []
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                        records = data if isinstance(data, list) else []
                    except Exception:
                        records = []

            records.append(record)

            # Atomic write: write to a sibling temp file then rename so a crash
            # mid-write never leaves a truncated history.json.
            dir_name = os.path.dirname(path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(records, f, indent=4)
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise
        except Exception as e:
            print(f"Failed to write history: {e}")

def load_history():
    """Loads all records from history.json."""
    path = get_history_file_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


