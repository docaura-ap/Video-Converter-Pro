"""
pywebview JS↔Python bridge.

All public methods are callable from JavaScript via window.pywebview.api.*
They run on a background thread so they must NOT touch the pywebview window
directly — use self._push() to dispatch events back to the JS layer.
"""

import os
import sys
import json
import threading
import tempfile
import atexit
import time
import shutil
import webview

# Reuse the existing production converter + utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from converter import ConversionManager, get_binary_path
from utils import (
    setup_logging, get_unique_output_path, get_file_size,
    detect_hardware_encoders, append_history, load_history, format_duration,
    open_logs_folder,
)

VIDEO_EXTS = {
    '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v',
    '.3gp', '.f4v', '.hevc', '.m2v', '.mjpeg', '.mpeg', '.mpg',
    '.mts', '.mxf', '.ogv', '.rm', '.ts', '.vob', '.wtv', '.y4m',
    '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma',
}

FORMAT_EXT = {
    'mp4': 'mp4', 'mkv': 'mkv', 'avi': 'avi', 'mov': 'mov',
    'webm': 'webm', 'mp4 (h.265)': 'mp4', 'mp3': 'mp3',
}


class Api:
    def __init__(self):
        self._window = None
        self._logger = setup_logging()
        self._converter = ConversionManager(self._logger)
        self._hw = detect_hardware_encoders()
        self._lock = threading.Lock()
        self._running = False
        self._pending = {}           # fid → metadata dict for in-progress conversions
        self._paused_states = {}     # fid → metadata dict for paused conversions
        self._temp_dir = tempfile.mkdtemp(prefix='vc_temp_')
        self._expected_done_count = 0  # tasks added but _done not yet called
        atexit.register(self._cleanup_temp_dir)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def set_window(self, win):
        self._window = win

    def _cleanup_temp_dir(self):
        """Remove the per-session temp directory — called via atexit and close_window."""
        try:
            if self._temp_dir and os.path.isdir(self._temp_dir):
                shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass

    def _push(self, data: dict):
        """Send a JSON event to the JS layer via CustomEvent."""
        if self._window:
            js = (
                "window.dispatchEvent(new CustomEvent('vc-update',"
                f"{{detail:{json.dumps(data)}}}));"
            )
            try:
                self._window.evaluate_js(js)
            except Exception as e:
                self._logger.warning(f"evaluate_js failed: {e}")

    # ── Window controls ──────────────────────────────────────────────────────

    def minimize_window(self):
        self._window.minimize()

    def toggle_maximize(self):
        self._window.toggle_fullscreen()

    def close_window(self):
        try:
            self._converter.stop_processing()
            # Give each terminated process up to 3 s to die before we destroy
            # the window — prevents zombie FFmpeg processes.
            deadline = time.time() + 3.0
            with self._converter.process_lock:
                procs = list(self._converter.active_processes.values())
            for proc in procs:
                remaining = max(0.05, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._cleanup_temp_dir()
        except Exception:
            pass
        self._window.destroy()

    # ── File / folder picking ────────────────────────────────────────────────

    def add_files(self):
        # Use tkinter file dialog — pywebview OPEN_DIALOG can silently fail on
        # Windows when called from the API background thread.
        import tkinter as tk
        from tkinter import filedialog
        exts = sorted(VIDEO_EXTS)
        filetypes = [
            ('Video & Audio', ' '.join(f'*{e}' for e in exts)),
            ('All files', '*.*'),
        ]
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        paths = filedialog.askopenfilenames(title='Select Video Files', filetypes=filetypes)
        root.destroy()
        if not paths:
            return []
        files = [self._file_info(p) for p in paths if os.path.isfile(p)]
        threading.Thread(target=self._probe_durations, args=(files,), daemon=True).start()
        return files

    def add_folder(self):
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return []
        folder = result[0] if isinstance(result, (list, tuple)) else result
        files = []
        for root, _, names in os.walk(folder):
            for name in sorted(names):
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_EXTS:
                    files.append(self._file_info(os.path.join(root, name)))
        threading.Thread(target=self._probe_durations, args=(files,), daemon=True).start()
        return files

    def _file_info(self, path: str) -> dict:
        """Return file metadata immediately — duration is probed separately."""
        name = os.path.splitext(os.path.basename(path))[0]
        ext  = os.path.splitext(path)[1].lstrip('.').lower()
        size = get_file_size(path)
        return {
            'path': path,
            'name': name,
            'ext':  ext,
            'size': size,
            'duration': 0,   # filled in by _probe_durations
            'status': 'queue',
            'progress': 0,
            'error': None,
        }

    def _probe_durations(self, files: list):
        """Run ffprobe for each file and push duration updates to the frontend."""
        for f in files:
            try:
                dur = self._converter._get_duration(f['path'])
                if dur > 0:
                    self._push({'type': 'duration', 'path': f['path'], 'duration': dur})
            except Exception:
                pass

    # ── Conversion control ───────────────────────────────────────────────────

    # Formats that encode to a temp MKV intermediate so pause/resume is lossless.
    # mp3 and avi are written directly (mp3 is streaming; avi audio codec mismatch).
    _TEMP_MKV_FORMATS = {'mp4', 'mkv', 'mov', 'webm', 'mp4 (h.265)'}

    def _temp_mkv_path(self, fid):
        return os.path.join(self._temp_dir, f'vc_{fid}_part.mkv')

    def _temp_mkv_path2(self, fid):
        return os.path.join(self._temp_dir, f'vc_{fid}_part2.mkv')

    def _cleanup_temp(self, *paths):
        for p in paths:
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def _add_one_task(self, fid, path, out_path, task_settings, target_ext,
                      delete_orig, max_workers, encode_to=None, part1_path=None,
                      base_progress_pct=0.0, total_duration=0.0, file_name=''):
        """
        Wire up progress/done callbacks and enqueue one conversion task.
        encode_to  – if set, ffmpeg writes here (temp MKV); on success we remux to out_path
        part1_path – if set, after encoding we concat part1+encode_to and remux to out_path
        base_progress_pct – starting progress for resumed files (0..100)
        """
        output_format = task_settings.get('format', 'mp4')
        actual_encode_to = encode_to or out_path

        with self._lock:
            self._pending[fid] = {
                'path': path,
                'output': out_path,
                'name': file_name or os.path.basename(path),
                'ext': os.path.splitext(path)[1].lstrip('.').lower(),
                'duration': total_duration,
                'delete_original': delete_orig,
                'temp_path': encode_to,      # None → direct output
                'part1_path': part1_path,    # None → not a resume
                'settings': task_settings,
            }
            self._expected_done_count += 1

        remaining_pct = 100.0 - base_progress_pct

        def _progress(pct, eta=0., spd=1., fps=0., _fid=fid,
                      _base=base_progress_pct, _rem=remaining_pct):
            scaled = _base + (pct / 100.0) * _rem
            self._push({'type': 'progress', 'id': _fid, 'progress': round(scaled, 1)})

        def _status(msg, color='primary', _fid=fid):
            pass

        def _done(inp, outp, success, _fid=fid, _fmt=output_format, _ext=target_ext,
                  _del=delete_orig):
            # Single atomic lock block: pop state AND decrement counter together
            # so queue_done fires exactly once even when files are snapshotted out
            # of _pending early (per-file pause), and count never goes negative.
            with self._lock:
                meta = self._pending.pop(_fid, None)
                paused_state = self._paused_states.get(_fid)
                self._expected_done_count -= 1
                fire_done = (self._expected_done_count <= 0)
                if fire_done:
                    self._running = False

            if meta is None:
                # Intentional pause — send paused event with last known position
                pos = self._converter.current_positions.get(inp, 0)
                if paused_state:
                    pos = paused_state.get('paused_at', pos)
                self._push({'type': 'paused', 'id': _fid, 'paused_at': pos})
                if fire_done:
                    self._push({'type': 'queue_done'})
                return

            dur_str = format_duration(meta.get('duration', 0))
            sz      = get_file_size(inp)
            final   = meta['output']
            tmp     = meta.get('temp_path')
            p1      = meta.get('part1_path')

            if success:
                # Remux/concat the temp MKV(s) into the final container
                ok = True
                if p1 and tmp:
                    ok = self._converter.concat_and_remux(p1, tmp, final, _fmt)
                    self._cleanup_temp(p1, tmp)
                elif tmp:
                    ok = self._converter.remux_to_output(tmp, final, _fmt)
                    self._cleanup_temp(tmp)

                if ok and os.path.isfile(final):
                    out_size = get_file_size(final)
                    self._push({'type': 'done', 'id': _fid,
                                'output_path': final, 'output_size': out_size})
                    append_history(meta.get('name', ''), _ext, sz, dur_str, 'Success')
                    if _del and os.path.isfile(inp):
                        try:
                            os.remove(inp)
                        except Exception as e:
                            self._logger.error(f"Delete original: {e}")
                else:
                    self._push({'type': 'error', 'id': _fid,
                                'error': 'Remux/concat failed'})
                    append_history(meta.get('name', ''), _ext, sz, dur_str,
                                   'Error: Remux failed')
            else:
                # Keep part1 temp on failure (user can retry) — only delete part2
                self._cleanup_temp(tmp)
                err = outp if isinstance(outp, str) else 'Conversion failed'
                self._push({'type': 'error', 'id': _fid, 'error': err})
                append_history(meta.get('name', ''), _ext, sz, dur_str,
                               f'Error: {err}')

            if fire_done:
                self._push({'type': 'queue_done'})

        self._converter.add_task(path, actual_encode_to, task_settings,
                                 _progress, _status, _done)

    def start_conversion(self, files, settings):
        """
        files    – list of {id, path, name, ext, duration, trim?}
        settings – {format, quality, gpu, parallel, keep_dir, delete_original,
                    name_template}
        Allowed while _running=True (e.g. resumed files already in the pool).
        New tasks are added to the live queue; workers pick them up automatically.
        """
        # Bridge validation: reject outright-wrong types from JS layer.
        if not isinstance(files, list):
            return False
        if not isinstance(settings, dict):
            settings = {}

        if not files:
            return True  # nothing to do; caller may still have resumed paused files

        output_format = settings.get('format', 'mp4')
        target_ext    = FORMAT_EXT.get(output_format, 'mp4')
        acceleration  = settings.get('gpu', 'CPU')
        quality       = settings.get('quality', 'High')
        try:
            max_workers = max(1, min(4, int(settings.get('parallel', 1))))
        except (TypeError, ValueError):
            max_workers = 1
        keep_dir      = settings.get('keep_dir', False)
        delete_orig   = settings.get('delete_original', False)
        name_tmpl     = settings.get('name_template', '{name}_converted')
        if not isinstance(name_tmpl, str):
            name_tmpl = '{name}_converted'
        name_tmpl = name_tmpl.strip() or '{name}'

        with self._lock:
            self._running = True
        reserved = set()

        for f in files:
            if not isinstance(f, dict) or 'id' not in f or 'path' not in f:
                continue
            fid  = f['id']
            path = f['path']
            if not isinstance(path, str) or not os.path.isfile(path):
                self._push({'type': 'error', 'id': fid,
                            'error': 'File not found on disk'})
                continue

            base = os.path.splitext(os.path.basename(path))[0]
            new_name = (name_tmpl.replace('{name}', base)
                        if '{name}' in name_tmpl else f"{base}_{name_tmpl}")
            # Strip Windows-invalid chars and common shell-special chars from filename
            for ch in '\\/:*?"<>|;&':
                new_name = new_name.replace(ch, '_')

            out_dir = (os.path.dirname(path) if keep_dir
                       else os.path.join(os.path.dirname(path), 'Converted'))
            os.makedirs(out_dir, exist_ok=True)

            out_path = get_unique_output_path(out_dir, new_name, target_ext,
                                              reserved=reserved)
            reserved.add(out_path)

            trim = f.get('trim')
            task_settings = {
                'format':      output_format,
                'acceleration': acceleration,
                'quality':     quality,
                'compress_percentage': 0,
                'start_time':  format_duration(trim['start']) if trim else '',
                'end_time':    format_duration(trim['end'])   if trim else '',
            }

            # Use MKV intermediate for formats that support true pause/resume
            use_temp = output_format in self._TEMP_MKV_FORMATS
            encode_to = self._temp_mkv_path(fid) if use_temp else None

            self._add_one_task(
                fid=fid, path=path, out_path=out_path,
                task_settings=task_settings, target_ext=target_ext,
                delete_orig=delete_orig, max_workers=max_workers,
                encode_to=encode_to, part1_path=None,
                base_progress_pct=0.0,
                total_duration=f.get('duration', 0),
                file_name=os.path.basename(path),
            )

        # start_processing is a no-op when workers are already active,
        # so it's always safe to call — new queue items are picked up automatically.
        self._converter.start_processing(max_workers)
        return True

    # ── Per-file pause ────────────────────────────────────────────────────────

    def _snapshot_pending_file(self, fid):
        """
        Caller MUST already hold self._lock.
        Pops fid from _pending and saves a paused-state entry so resume works.
        Returns the input_path so the caller can terminate the correct process.
        """
        meta = self._pending.pop(fid, None)
        if meta is None:
            return None

        input_path = meta['path']
        pos = self._converter.current_positions.get(input_path, 0)

        self._paused_states[fid] = {
            'fid':            fid,
            'input':          input_path,
            'output':         meta['output'],
            'name':           meta.get('name', ''),
            'ext':            meta.get('ext', ''),
            'duration':       meta.get('duration', 0),
            'settings':       meta.get('settings', {}),
            'part1_temp':     meta.get('temp_path') or '',
            'paused_at':      pos,
            'delete_original': meta.get('delete_original', False),
        }
        return input_path

    def pause_file(self, fid):
        """Pause the conversion of a single file identified by its frontend id."""
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return False
        with self._lock:
            inp = self._snapshot_pending_file(fid)

        if inp:
            with self._converter.process_lock:
                proc = self._converter.active_processes.get(inp)
                if proc and proc.poll() is None:
                    proc.terminate()
        return True

    def pause_conversion(self):
        """Pause all in-progress files and stop the worker pool."""
        # Snapshot every pending file while holding the lock — no nested lock calls.
        with self._lock:
            for fid in list(self._pending.keys()):
                self._snapshot_pending_file(fid)  # safe: no inner lock acquisition

        self._converter.stop_processing()
        with self._lock:
            self._running = False
        return True

    # ── Per-file resume ───────────────────────────────────────────────────────

    def resume_file(self, fid):
        """
        Resume a previously paused file from the exact position it was paused at.
        Encodes the remaining segment to a second temp MKV, then on completion
        concatenates both parts and remuxes to the final output format.
        """
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return False
        with self._lock:
            state = self._paused_states.pop(fid, None)
        if not state:
            return False

        inp = state['input']

        # Wait up to 500 ms for any still-running FFmpeg on this input to die.
        # pause_file terminates the process but the OS may not have reaped it yet;
        # starting a second FFmpeg on the same file before the first exits causes
        # two concurrent encoders reading the same source.
        deadline = time.time() + 0.5
        while time.time() < deadline:
            with self._converter.process_lock:
                proc = self._converter.active_processes.get(inp)
            if proc is None or proc.poll() is not None:
                break
            time.sleep(0.025)

        out_path   = state['output']
        duration   = state['duration']
        settings   = state['settings'].copy()
        part1_temp = state.get('part1_temp', '')
        paused_at  = state.get('paused_at', 0)
        output_format = settings.get('format', 'mp4')
        target_ext    = FORMAT_EXT.get(output_format, 'mp4')
        delete_orig   = state.get('delete_original', False)

        # Probe actual encoded length of part1 (kill timing ≠ last reported time=)
        actual_p1_end = 0.0
        if part1_temp and os.path.isfile(part1_temp):
            actual_p1_end = self._converter.probe_file_duration(part1_temp)
            if actual_p1_end <= 0:
                actual_p1_end = paused_at   # fallback
        else:
            part1_temp = ''   # part1 doesn't exist, encode everything

        resume_from = actual_p1_end if part1_temp else 0.0
        base_pct    = (resume_from / duration * 100) if duration > 0 else 0.0

        # Temp file for the new (resumed) segment
        part2_temp = self._temp_mkv_path2(fid)

        settings['resume_from_secs'] = resume_from

        with self._lock:
            self._running = True
        self._add_one_task(
            fid=fid, path=inp, out_path=out_path,
            task_settings=settings, target_ext=target_ext,
            delete_orig=delete_orig, max_workers=1,
            encode_to=part2_temp,
            part1_path=part1_temp or None,
            base_progress_pct=base_pct,
            total_duration=duration,
            file_name=state.get('name', os.path.basename(inp)),
        )
        self._converter.start_processing(max_workers=1)

        # Tell the frontend to re-enter "converting" state at the current progress
        self._push({'type': 'resumed', 'id': fid, 'progress': round(base_pct, 1)})
        return True

    def clear_paused_states(self):
        """Called when the user clears the queue — discard all paused temp files."""
        with self._lock:
            for state in self._paused_states.values():
                self._cleanup_temp(state.get('part1_temp', ''))
            self._paused_states.clear()
        return True

    # ── History ──────────────────────────────────────────────────────────────

    def get_history(self):
        records = load_history()
        # Return newest first
        return list(reversed(records))

    def clear_history(self):
        from utils import get_history_file_path
        path = get_history_file_path()
        try:
            import json as _json
            with open(path, 'w', encoding='utf-8') as f:
                _json.dump([], f)
        except Exception:
            pass
        return True

    # ── Engine info ──────────────────────────────────────────────────────────

    def get_engine_info(self):
        ffmpeg = get_binary_path('ffmpeg.exe')
        version = '—'
        try:
            import subprocess
            r = subprocess.run([ffmpeg, '-version'], capture_output=True,
                               text=True, timeout=5,
                               creationflags=0x08000000 if os.name == 'nt' else 0)
            first = r.stdout.splitlines()[0] if r.stdout else ''
            # e.g. "ffmpeg version 7.1 Copyright..."
            parts = first.split()
            version = parts[2] if len(parts) >= 3 else first
        except Exception:
            pass

        hw = self._hw
        return [
            {'k': 'Engine',       'v': f'FFmpeg {version} (bundled)', 'status': None},
            {'k': 'NVIDIA NVENC', 'v': 'Available' if hw.get('NVIDIA (NVENC)') else 'Not detected',
             'status': 'ok' if hw.get('NVIDIA (NVENC)') else None},
            {'k': 'Intel QSV',   'v': 'Available' if hw.get('Intel (QSV)')    else 'Not detected',
             'status': 'ok' if hw.get('Intel (QSV)')    else None},
            {'k': 'AMD AMF',     'v': 'Available' if hw.get('AMD (AMF)')       else 'Not detected',
             'status': 'ok' if hw.get('AMD (AMF)')       else None},
        ]

    # ── File utilities ───────────────────────────────────────────────────────

    def open_output_folder(self, path):
        if not isinstance(path, str):
            return True
        folder = os.path.dirname(path) if os.path.isfile(path) else path
        if os.path.isdir(folder):
            os.startfile(folder)
        return True

    def open_logs_folder(self):
        open_logs_folder()
        return True
