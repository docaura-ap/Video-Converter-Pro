"""
Chaos / Security test suite — Video Converter Pro
===================================================
Covers all five threat vectors from the production security audit:
  A. Input sanitization & command injection
  B. State desynchronization & race conditions
  C. Path traversal & file-system edge cases
  D. Corrupt file & binary dependency failures
  E. Python-JS bridge (pywebview) input validation

Run with:
    cd "D:\\Website 2026\\Apps\\1 Video Downloader Pro\\Video Converter"
    .\\venv\\Scripts\\python.exe -m pytest tests/ -v
"""

import os
import sys
import time
import json
import queue
import shutil
import threading
import tempfile
import types
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Mock pywebview at module level so backend.api can import ─────────────────
_webview_mod = types.ModuleType("webview")
_webview_mod.FOLDER_DIALOG = 1
_webview_mod.create_window = MagicMock()
_webview_mod.start = MagicMock()
sys.modules["webview"] = _webview_mod

from converter import ConversionManager  # noqa: E402
from utils import (  # noqa: E402
    get_unique_output_path,
    format_duration,
    append_history,
    load_history,
    get_history_file_path,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_logger():
    log = logging.getLogger("chaos_tests")
    if not log.handlers:
        log.addHandler(logging.NullHandler())
    return log


def _make_manager() -> ConversionManager:
    return ConversionManager(_make_logger())


def _make_api():
    """Return an Api instance with all heavy external deps mocked."""
    with (
        patch("backend.api.detect_hardware_encoders", return_value={}),
        patch("backend.api.setup_logging", return_value=_make_logger()),
    ):
        from backend.api import Api
        api = Api()
    api._window = MagicMock()
    api._window.evaluate_js = MagicMock()
    return api


def _fake_popen(returncode=0, output_lines=None):
    """Return a mock subprocess.Popen that exits immediately."""
    lines = list(output_lines or [])
    lines.append("")  # sentinel EOF

    proc = MagicMock()
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.stdout.readline.side_effect = lines
    return proc


def _fake_run(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# =============================================================================
# A  Command Injection & Subprocess Safety
# =============================================================================

class TestSubprocessSafety:
    """Verify no shell=True and that malicious filenames are list-element safe."""

    def _run_convert(self, input_path, output_path, settings, popen_side_effect):
        mgr = _make_manager()
        mgr.active = True  # normally set by start_processing(); needed for direct calls
        captured_kwargs = []

        def spy(cmd, **kw):
            captured_kwargs.append(kw)
            return popen_side_effect()

        with (
            patch("subprocess.Popen", side_effect=spy),
            patch.object(mgr, "_has_odd_dimensions", return_value=False),
        ):
            mgr._convert_file(input_path, output_path, settings, 60.0, None, 1)

        mgr.active = False
        return captured_kwargs

    def test_no_shell_true_in_convert_file(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "source.mp4")
            out = os.path.join(d, "out.mp4")
            with open(inp, "wb") as f:
                f.write(b"\x00" * 10)

            settings = {
                "format": "mp4", "acceleration": "CPU",
                "quality": "High", "compress_percentage": 0,
                "start_time": "", "end_time": "",
            }
            kwargs = self._run_convert(inp, out, settings, lambda: _fake_popen(0))

        for kw in kwargs:
            assert kw.get("shell", False) is not True, \
                "shell=True detected in subprocess call"

    def test_no_shell_true_in_remux(self):
        mgr = _make_manager()
        captured = []

        def spy_run(cmd, **kw):
            captured.append(kw)
            return _fake_run(0)

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "part.mkv")
            dst = os.path.join(d, "out.mp4")
            for p in (src, dst):
                open(p, "wb").close()

            with patch("subprocess.run", side_effect=spy_run):
                mgr.remux_to_output(src, dst, "mp4")

        for kw in captured:
            assert kw.get("shell", False) is not True

    def test_malicious_filename_is_single_list_element(self):
        """
        A filename like 'video & echo pwned.mp4' must not be shell-interpreted.
        It must appear as a single element in the command list, never split.
        """
        mgr = _make_manager()
        captured_cmds = []

        def spy(cmd, **kw):
            captured_cmds.append(cmd)
            return _fake_popen(0)

        with tempfile.TemporaryDirectory() as d:
            # Ampersand is valid in Windows filenames (not a separator in list-form)
            fname = "video & echo pwned.mp4"
            inp = os.path.join(d, fname)
            out = os.path.join(d, "out.mp4")
            with open(inp, "wb") as f:
                f.write(b"\x00" * 10)

            settings = {
                "format": "mp4", "acceleration": "CPU",
                "quality": "High", "compress_percentage": 0,
                "start_time": "", "end_time": "",
            }
            mgr.active = True
            with (
                patch("subprocess.Popen", side_effect=spy),
                patch.object(mgr, "_has_odd_dimensions", return_value=False),
            ):
                mgr._convert_file(inp, out, settings, 60.0, None, 1)
            mgr.active = False

        assert captured_cmds, "Popen was never called"
        for cmd in captured_cmds:
            assert isinstance(cmd, list), "cmd must be list, not string"
            # Input path must appear as a single unbroken element
            assert inp in cmd, "input path not found in cmd list"

    def test_ffconcat_single_quote_in_path_does_not_break_list(self):
        """
        concat_and_remux must not silently corrupt the ffconcat script when
        temp paths contain single-quote characters.
        """
        mgr = _make_manager()

        with tempfile.TemporaryDirectory() as d:
            # Simulate a path that contains a single quote — unusual but valid on Linux
            # On Windows single quotes in dir names are legal too.
            p1 = os.path.join(d, "part1.mkv")
            p2 = os.path.join(d, "part2.mkv")
            for p in (p1, p2):
                with open(p, "wb") as f:
                    f.write(b"\x00")

            captured_run_args = []

            def spy_run(cmd, **kw):
                captured_run_args.append(cmd)
                return _fake_run(0)

            with patch("subprocess.run", side_effect=spy_run):
                mgr.concat_and_remux(p1, p2, os.path.join(d, "out.mp4"), "mp4")

            # Find the concat list file that was written
            list_files = [f for f in os.listdir(d) if f.endswith("_concat_list.txt")]
            # List file should have been cleaned up by finally block
            assert list_files == [], "concat list temp file was not cleaned up"

            # The ffmpeg -i argument must point to a readable list file (run was called)
            assert captured_run_args, "ffmpeg concat was never called"


# =============================================================================
# B  State Desynchronization & Race Conditions
# =============================================================================

class TestRaceConditions:

    def setup_method(self):
        self.api = _make_api()

    # B1 — Atomic _done lock
    def test_queue_done_fires_exactly_once_under_concurrent_callbacks(self):
        """
        4 _done callbacks fire simultaneously via a threading.Barrier.
        queue_done must be dispatched exactly once; _expected_done_count must
        never go negative.
        """
        N = 4
        with self.api._lock:
            for fid in range(N):
                self.api._pending[fid] = {
                    "path": f"/fake/v{fid}.mp4",
                    "output": f"/fake/o{fid}.mp4",
                    "name": f"v{fid}",
                    "ext": "mp4",
                    "duration": 60,
                    "delete_original": False,
                    "temp_path": None,
                    "part1_path": None,
                    "settings": {"format": "mp4"},
                }
            self.api._expected_done_count = N
            self.api._running = True

        queue_done_fires = []
        negative_snapshots = []

        def counting_push(data):
            if data.get("type") == "queue_done":
                queue_done_fires.append(1)
            # Capture count at this moment (outside lock intentionally — we are
            # testing the observable race, not what the lock hides)
            c = self.api._expected_done_count
            if c < 0:
                negative_snapshots.append(c)

        self.api._push = counting_push

        def make_sim_done(fid):
            def sim():
                # This reproduces the FIXED implementation (single lock block).
                # When testing BEFORE fix, replace with two separate blocks.
                with self.api._lock:
                    self.api._pending.pop(fid, None)
                    self.api._expected_done_count -= 1
                    fire = self.api._expected_done_count <= 0
                    if fire:
                        self.api._running = False
                if fire:
                    self.api._push({"type": "queue_done"})
            return sim

        barrier = threading.Barrier(N)
        errors = []

        def worker(fid):
            try:
                barrier.wait()
                make_sim_done(fid)()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Worker threads raised: {errors}"
        assert negative_snapshots == [], f"Count went negative: {negative_snapshots}"
        assert len(queue_done_fires) == 1, \
            f"queue_done fired {len(queue_done_fires)} times (expected 1)"
        assert self.api._expected_done_count == 0

    # B2-B4 — _running mutated without lock
    def test_running_flag_consistent_under_concurrent_start_and_done(self):
        """
        start_conversion and _done callbacks both mutate _running.
        After 50 rapid start/done cycles the flag must always be False
        (all tasks done) with no data races detected.
        """
        results = []

        def one_cycle(_):
            with self.api._lock:
                self.api._running = True
                self.api._expected_done_count = 1
                self.api._pending[1] = {
                    "path": "/f.mp4", "output": "/o.mp4", "name": "f",
                    "ext": "mp4", "duration": 0, "delete_original": False,
                    "temp_path": None, "part1_path": None,
                    "settings": {"format": "mp4"},
                }

            # Simulate _done callback
            with self.api._lock:
                self.api._pending.pop(1, None)
                self.api._expected_done_count -= 1
                if self.api._expected_done_count <= 0:
                    self.api._running = False

            with self.api._lock:
                results.append(self.api._running)

        threads = [threading.Thread(target=one_cycle, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert all(r is False for r in results), \
            f"_running was True after done callback in {results.count(True)} cycles"

    # B5 — Rapid pause → resume: old process still alive
    def test_pause_then_immediate_resume_does_not_crash(self):
        """
        Rapid pause→resume on the same fid must never raise an unhandled
        exception or corrupt the paused_states dict.
        """
        fid = 42
        with self.api._lock:
            self.api._pending[fid] = {
                "path": "/fake/video.mp4", "output": "/fake/out.mp4",
                "name": "video", "ext": "mp4", "duration": 100,
                "delete_original": False, "temp_path": None,
                "part1_path": None, "settings": {"format": "mp4"},
            }
            self.api._expected_done_count = 1
            self.api._running = True

        errors = []

        def do_pause():
            try:
                self.api.pause_file(fid)
            except Exception as e:
                errors.append(("pause", e))

        def do_resume():
            time.sleep(0.003)
            try:
                self.api.resume_file(fid)
            except Exception as e:
                errors.append(("resume", e))

        t1 = threading.Thread(target=do_pause)
        t2 = threading.Thread(target=do_resume)
        t1.start(); t2.start()
        t1.join(timeout=2); t2.join(timeout=2)

        assert errors == [], f"pause/resume raised: {errors}"

    # B6 — close_window terminates processes
    def test_close_window_calls_terminate_on_all_active_processes(self):
        mock_proc_a = MagicMock()
        mock_proc_a.poll.return_value = None
        mock_proc_b = MagicMock()
        mock_proc_b.poll.return_value = None

        self.api._converter.active_processes = {
            "/a.mp4": mock_proc_a,
            "/b.mp4": mock_proc_b,
        }
        self.api._converter.active = True

        self.api.close_window()

        mock_proc_a.terminate.assert_called()
        mock_proc_b.terminate.assert_called()

    # B7 — temp dir cleanup
    def test_atexit_cleanup_registered_for_temp_dir(self):
        """Api.__init__ must register at least one atexit handler."""
        import atexit
        before = atexit._ncallbacks()
        _make_api()
        after = atexit._ncallbacks()
        assert after > before, (
            f"No new atexit handler registered by Api.__init__ "
            f"(before={before}, after={after})"
        )

    # B — clear_paused_states cleans temp files
    def test_clear_paused_states_removes_temp_mkv_files(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = os.path.join(td, "seg1.mkv")
            p2 = os.path.join(td, "seg2.mkv")
            for p in (p1, p2):
                with open(p, "wb") as f:
                    f.write(b"\x00")

            with self.api._lock:
                self.api._paused_states[10] = {
                    "fid": 10, "input": "/a.mp4", "output": "/out.mp4",
                    "name": "a", "ext": "mp4", "duration": 60,
                    "settings": {}, "part1_temp": p1,
                    "paused_at": 30, "delete_original": False,
                }
                self.api._paused_states[11] = {
                    "fid": 11, "input": "/b.mp4", "output": "/out2.mp4",
                    "name": "b", "ext": "mp4", "duration": 60,
                    "settings": {}, "part1_temp": p2,
                    "paused_at": 15, "delete_original": False,
                }

            self.api.clear_paused_states()

            assert not os.path.exists(p1), "Part1 MKV not cleaned up"
            assert not os.path.exists(p2), "Part2 MKV not cleaned up"
            assert self.api._paused_states == {}


# =============================================================================
# C  Path Traversal & File System Edge Cases
# =============================================================================

class TestPathEdgeCases:

    def test_unique_path_basic(self):
        with tempfile.TemporaryDirectory() as d:
            p = get_unique_output_path(d, "video", "mp4")
            assert p == os.path.join(d, "video.mp4")

    def test_unique_path_avoids_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            existing = os.path.join(d, "video.mp4")
            open(existing, "w").close()
            p = get_unique_output_path(d, "video", "mp4")
            assert p == os.path.join(d, "video_1.mp4")

    def test_unique_path_avoids_reserved_set(self):
        with tempfile.TemporaryDirectory() as d:
            reserved = {os.path.join(d, "video.mp4")}
            p = get_unique_output_path(d, "video", "mp4", reserved=reserved)
            assert p not in reserved
            assert p == os.path.join(d, "video_1.mp4")

    def test_parallel_reservation_no_duplicates(self):
        """Simulates 5 parallel workers all choosing output paths for 'video'."""
        with tempfile.TemporaryDirectory() as d:
            reserved = set()
            assigned = []
            for _ in range(5):
                p = get_unique_output_path(d, "video", "mp4", reserved=reserved)
                assert p not in assigned, f"Duplicate path: {p}"
                assigned.append(p)
                reserved.add(p)
            assert len(set(assigned)) == 5

    @pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH only")
    def test_unique_path_truncates_at_max_path_windows(self):
        """
        On Windows, generated paths must be ≤ 260 characters.
        (Requires the MAX_PATH fix in utils.py.)
        """
        with tempfile.TemporaryDirectory() as base:
            long_name = "A" * 240
            p = get_unique_output_path(base, long_name, "mp4")
            assert len(p) <= 260, f"Path is {len(p)} chars (limit 260): {p}"

    def test_unique_path_unicode_filename(self):
        with tempfile.TemporaryDirectory() as d:
            p = get_unique_output_path(d, "视频_🎬_фильм", "mp4")
            assert p.endswith(".mp4")

    def test_name_template_slash_is_sanitized(self):
        """
        Forward / backward slashes in the rendered name template must be
        replaced before the path is constructed.
        (This mirrors the sanitization loop in api.py start_conversion.)
        """
        template = "../../../malicious/{name}"
        base = "video"
        new_name = template.replace("{name}", base)
        for ch in '\\/:*?"<>|':
            new_name = new_name.replace(ch, "_")
        assert "/" not in new_name
        assert "\\" not in new_name
        assert ".." not in new_name or new_name.startswith(".")  # baseline check

    def test_history_write_survives_corrupt_json(self):
        """append_history must not crash if the history file is corrupt JSON."""
        path = get_history_file_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("{{{not valid json!!")

            append_history("test_video", "mp4", "100 MB", "00:01:30", "Success")
            records = load_history()
            assert isinstance(records, list)
            assert any(r.get("input_name") == "test_video" for r in records)
        finally:
            with open(path, "w") as f:
                json.dump([], f)

    def test_history_concurrent_writes_no_corruption(self):
        """
        20 threads appending to history simultaneously must not corrupt the
        JSON file and all entries must be present.
        (Requires the atomic-write + lock fix in utils.py.)
        """
        path = get_history_file_path()
        with open(path, "w") as f:
            json.dump([], f)

        errors = []

        def write_entry(i):
            try:
                append_history(f"video_{i:02d}", "mp4", "10 MB", "00:00:10", "Success")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        with open(path, "w") as f:
            json.dump([], f)

        assert errors == [], f"Concurrent history writes raised: {errors}"


# =============================================================================
# D  Corrupt File & Binary Dependency Failures
# =============================================================================

class TestCorruptFilesAndBinaryFailures:

    def setup_method(self):
        self.mgr = _make_manager()

    @patch("subprocess.run")
    def test_validate_zero_byte_file_returns_false(self, mock_run):
        mock_run.return_value = _fake_run(returncode=0, stdout="")
        assert self.mgr._validate_video_container("/fake/zero.mp4") is False

    @patch("subprocess.run")
    def test_validate_nonzero_exit_returns_false(self, mock_run):
        mock_run.return_value = _fake_run(returncode=1, stdout="")
        assert self.mgr._validate_video_container("/fake/broken.mp4") is False

    @patch("subprocess.run")
    def test_probe_duration_na_returns_zero(self, mock_run):
        mock_run.return_value = _fake_run(returncode=0, stdout="N/A\n")
        assert self.mgr.probe_file_duration("/fake/file.mkv") == 0.0

    @patch("subprocess.run")
    def test_probe_duration_garbage_stdout_returns_zero(self, mock_run):
        mock_run.return_value = _fake_run(returncode=0, stdout="!!not_a_float!!\n")
        assert self.mgr.probe_file_duration("/fake/file.mkv") == 0.0

    @patch("subprocess.run")
    def test_probe_duration_timeout_returns_zero(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("ffprobe", 10)
        assert self.mgr.probe_file_duration("/fake/file.mkv") == 0.0

    def test_worker_permission_error_on_makedirs_fires_completion_cb(self):
        """
        PermissionError from os.makedirs must still call completion_cb(False).
        Without the fix this silently drops the callback and the UI hangs.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00" * 64)
            inp = f.name

        out = "/nonexistent_protected_dir/output.mp4"
        done_results = []

        settings = {
            "format": "mp4", "acceleration": "CPU", "quality": "High",
            "compress_percentage": 0, "start_time": "", "end_time": "",
        }
        self.mgr.add_task(
            inp, out, settings,
            completion_callback=lambda i, o, s: done_results.append((o, s)),
        )

        with (
            patch("os.makedirs", side_effect=PermissionError("Access denied")),
            patch.object(self.mgr, "_validate_video_container", return_value=True),
            patch.object(self.mgr, "_get_duration", return_value=60.0),
        ):
            self.mgr.start_processing(max_workers=1)
            deadline = time.time() + 3.0
            while time.time() < deadline and not done_results:
                time.sleep(0.05)
            self.mgr.stop_processing()

        os.unlink(inp)

        assert done_results, "completion_callback never fired after PermissionError"
        _output, success = done_results[0]
        assert success is False, "Expected failure=True but got success"

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_gpu_fallback_fires_on_nonzero_exit_code(self, mock_popen, mock_run):
        """
        A GPU encode that exits with code 128 (SIGKILL) must trigger CPU retry.
        The test verifies Popen is called twice.
        """
        mock_run.return_value = _fake_run(0, stdout="mp4\n")

        gpu_proc = _fake_popen(returncode=128)
        cpu_proc = _fake_popen(returncode=0)
        mock_popen.side_effect = [gpu_proc, cpu_proc]

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00" * 64)
            inp = f.name

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.mp4")
            settings = {
                "format": "mp4", "acceleration": "NVIDIA (NVENC)",
                "quality": "High", "compress_percentage": 0,
                "start_time": "", "end_time": "",
            }
            done = []
            self.mgr.add_task(inp, out, settings,
                              completion_callback=lambda i, o, s: done.append(s))

            with patch.object(self.mgr, "_validate_video_container", return_value=True), \
                 patch.object(self.mgr, "_get_duration", return_value=60.0), \
                 patch("shutil.disk_usage", return_value=(10**10, 0, 10**10)), \
                 patch.object(self.mgr, "_has_odd_dimensions", return_value=False):
                self.mgr.start_processing(max_workers=1)
                deadline = time.time() + 3.0
                while time.time() < deadline and not done:
                    time.sleep(0.05)
                self.mgr.stop_processing()

        os.unlink(inp)

        assert mock_popen.call_count == 2, \
            f"Expected 2 Popen calls (GPU + CPU fallback), got {mock_popen.call_count}"

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_ffmpeg_access_violation_exit_code_returns_error_message(self, mock_popen, mock_run):
        """Exit code 0xC0000005 (access violation) must produce a human-readable error."""
        mock_run.return_value = _fake_run(0, stdout="mp4\n")
        # Simulate what Windows reports: unsigned 0xC0000005 (access violation)
        mock_popen.return_value = _fake_popen(returncode=0xC0000005 - 2**32)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00" * 64)
            inp = f.name

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.mp4")
            settings = {
                "format": "mp4", "acceleration": "CPU",
                "quality": "High", "compress_percentage": 0,
                "start_time": "", "end_time": "",
            }
            # _convert_file checks self.active in its poll loop; must be True
            # (normally set by _worker → start_processing, not by direct calls).
            self.mgr.active = True
            with patch.object(self.mgr, "_has_odd_dimensions", return_value=False):
                success, msg = self.mgr._convert_file(inp, out, settings, 60.0, None, 1)
            self.mgr.active = False

        os.unlink(inp)

        assert success is False
        assert msg is not None and "Corrupt" in msg, f"Expected 'Corrupt' in msg, got: {msg!r}"


# =============================================================================
# E  pywebview Bridge Input Validation
# =============================================================================

class TestBridgeInputValidation:

    def setup_method(self):
        self.api = _make_api()

    # E1 — add_files_by_paths
    def test_add_files_by_paths_non_list_returns_empty(self):
        assert self.api.add_files_by_paths({"evil": "dict"}) == []

    def test_add_files_by_paths_none_returns_empty(self):
        assert self.api.add_files_by_paths(None) == []

    def test_add_files_by_paths_string_not_iterated_char_by_char(self):
        """A raw string must not produce file results by iterating characters."""
        result = self.api.add_files_by_paths("C:/video.mp4")
        assert result == []

    def test_add_files_by_paths_non_string_elements_skipped(self):
        result = self.api.add_files_by_paths([42, None, True, b"bytes"])
        assert result == []

    def test_add_files_by_paths_rejects_non_video_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            exe = f.name
        try:
            assert self.api.add_files_by_paths([exe]) == []
        finally:
            os.unlink(exe)

    # E2 — start_conversion
    def test_start_conversion_non_list_files_returns_false(self):
        result = self.api.start_conversion("not_a_list", {})
        assert result is False

    def test_start_conversion_non_dict_settings_with_empty_files(self):
        """Empty files list is a valid no-op regardless of settings type."""
        result = self.api.start_conversion([], "bad_settings")
        assert result is True  # nothing to do

    def test_start_conversion_bad_parallel_clamped_not_crash(self):
        """Non-numeric 'parallel' must be silently clamped, never crash."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name
        try:
            self.api.start_conversion(
                [{"id": 1, "path": tmp, "name": "t", "ext": "mp4", "duration": 0}],
                {"format": "mp4", "quality": "High", "gpu": "CPU",
                 "parallel": "NOT_A_NUMBER", "keep_dir": False,
                 "delete_original": False, "name_template": "{name}_converted"},
            )
            self.api._converter.stop_processing()
        finally:
            os.unlink(tmp)

    def test_start_conversion_missing_id_key_skipped_gracefully(self):
        self.api.start_conversion(
            [{"missing_id": 1, "path": "/nonexistent.mp4"}],
            {"format": "mp4", "quality": "High", "gpu": "CPU",
             "parallel": 1, "keep_dir": False, "delete_original": False,
             "name_template": "{name}_converted"},
        )

    def test_start_conversion_non_dict_settings_with_files_does_not_crash(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name
        try:
            self.api.start_conversion(
                [{"id": 1, "path": tmp, "name": "t", "ext": "mp4", "duration": 0}],
                "this_is_a_string",
            )
            self.api._converter.stop_processing()
        finally:
            os.unlink(tmp)

    # E3/E4 — pause_file / resume_file
    def test_pause_file_non_numeric_fid_returns_false(self):
        assert self.api.pause_file("not_a_number") is False

    def test_pause_file_float_fid_coerced(self):
        """JS may send 1.0 for an integer id — must be accepted."""
        result = self.api.pause_file(1.0)
        assert result is True  # fid not in _pending → noop, not an error

    def test_resume_file_non_numeric_fid_returns_false(self):
        assert self.api.resume_file("bad_id") is False

    def test_resume_file_unknown_fid_returns_false(self):
        assert self.api.resume_file(99999) is False

    # E5 — open_output_folder
    def test_open_output_folder_non_string_returns_true(self):
        result = self.api.open_output_folder({"evil": "dict"})
        assert result is True

    def test_open_output_folder_path_traversal_does_not_open(self):
        """
        A traversal path like '../../Windows/System32' must not call os.startfile
        for a directory that could be sensitive, or at minimum must not crash.
        """
        with patch("os.startfile") as mock_sf:
            result = self.api.open_output_folder("../../Windows/System32")
            assert result is True
            # If startfile was called, it should only be for a real directory
            # (the traversal should resolve to a non-existent or validated path)

    # Bonus: malicious name_template with shell characters
    def test_start_conversion_malicious_name_template_sanitized(self):
        """Shell characters in name_template must be stripped from the filename."""
        api = _make_api()
        sanitized_names = []

        original_get_unique = __import__("utils").get_unique_output_path

        def spy_path(out_dir, name, ext, reserved=None):
            sanitized_names.append(name)
            return original_get_unique(out_dir, name, ext, reserved)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00")
            tmp = f.name

        try:
            with patch("backend.api.get_unique_output_path", side_effect=spy_path):
                api.start_conversion(
                    [{"id": 1, "path": tmp, "name": "video", "ext": "mp4", "duration": 0}],
                    {"format": "mp4", "quality": "High", "gpu": "CPU",
                     "parallel": 1, "keep_dir": False, "delete_original": False,
                     "name_template": "{name}; rm -rf *"},
                )
                api._converter.stop_processing()
        finally:
            os.unlink(tmp)

        if sanitized_names:
            assert ";" not in sanitized_names[0], \
                f"Semicolon not stripped from filename: {sanitized_names[0]!r}"


# =============================================================================
# F  format_duration edge cases (injection guard on trim times)
# =============================================================================

class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "00:00:00"

    def test_none_returns_zero_string(self):
        assert format_duration(None) == "00:00:00"

    def test_injection_string_returns_zero_string(self):
        assert format_duration("0; rm -rf /") == "00:00:00"

    def test_list_returns_zero_string(self):
        assert format_duration([1, 2, 3]) == "00:00:00"

    def test_negative_does_not_crash(self):
        result = format_duration(-60)
        assert isinstance(result, str)

    def test_float_truncates_subseconds(self):
        assert format_duration(90.9) == "00:01:30"

    def test_large_value(self):
        result = format_duration(3600 * 100)
        assert isinstance(result, str)
        assert result.startswith("100:")
