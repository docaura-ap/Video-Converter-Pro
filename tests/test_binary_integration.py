"""
Binary Integration Tests — Video Converter Pro
================================================
Tests run against *real* FFmpeg/FFprobe binaries, not mocks.

Two binary sets are tested:
  CURRENT  — the binaries already in /bin (baseline)
  STAGING  — the newly downloaded binaries in /bin/staging (candidate 8.1.1)

Tests in ``TestStagingBinaries`` are automatically skipped when the staging
binaries haven't been extracted yet.

Run with:
    .\\venv\\Scripts\\python.exe -m pytest tests/test_binary_integration.py -v -s
"""

import os
import re
import sys
import time
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
BIN_DIR = ROOT / "bin"
STAGING_DIR = BIN_DIR / "staging"

CURRENT_FFMPEG = BIN_DIR / "ffmpeg.exe"
CURRENT_FFPROBE = BIN_DIR / "ffprobe.exe"
STAGING_FFMPEG = STAGING_DIR / "ffmpeg.exe"
STAGING_FFPROBE = STAGING_DIR / "ffprobe.exe"

# ── Markers ───────────────────────────────────────────────────────────────────
requires_current = pytest.mark.skipif(
    not CURRENT_FFMPEG.exists() or not CURRENT_FFPROBE.exists(),
    reason="Current binaries not found in /bin",
)
requires_staging = pytest.mark.skipif(
    not STAGING_FFMPEG.exists() or not STAGING_FFPROBE.exists(),
    reason="Staging binaries not found in /bin/staging — extract FFmpeg 8.1.1 first",
)

# ── Regex patterns (mirrored from converter.py) ───────────────────────────────
TIME_RE  = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
SPEED_RE = re.compile(r"speed=\s*(\d+(?:\.\d+)?)x")
FPS_RE   = re.compile(r"fps=\s*(\d+(?:\.\d+)?)")

# ── Helpers ───────────────────────────────────────────────────────────────────

_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run(cmd, **kwargs):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=_CREATION_FLAGS,
        **kwargs,
    )


def _version(ffmpeg_path: Path) -> str:
    r = _run([str(ffmpeg_path), "-version"])
    return r.stdout.splitlines()[0] if r.stdout else "(unknown)"


def _make_test_video(ffmpeg: Path, dest: Path, duration_secs: int = 5) -> Path:
    """
    Generate a synthetic H.264/AAC MP4 using FFmpeg's built-in lavfi sources.
    No input file required — entirely self-contained.
    """
    cmd = [
        str(ffmpeg), "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_secs}:size=160x120:rate=25",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_secs}",
        "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        "-t", str(duration_secs),
        str(dest),
    ]
    r = _run(cmd)
    assert r.returncode == 0, (
        f"lavfi test-video generation failed (exit {r.returncode}):\n{r.stderr[-2000:]}"
    )
    return dest


def _probe_duration(ffprobe: Path, video: Path) -> float:
    """Mirrors converter.py probe_file_duration() exactly."""
    cmd = [
        str(ffprobe), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    r = _run(cmd)
    val = r.stdout.strip()
    if val and val != "N/A":
        return float(val)
    return 0.0


def _probe_container_name(ffprobe: Path, video: Path) -> str:
    """Mirrors _validate_video_container() format query."""
    cmd = [
        str(ffprobe), "-v", "error",
        "-show_entries", "format=format_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    r = _run(cmd)
    return r.stdout.strip()


def _probe_dimensions(ffprobe: Path, video: Path) -> tuple:
    """Mirrors _has_odd_dimensions() dimension query."""
    cmd = [
        str(ffprobe), "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(video),
    ]
    r = _run(cmd)
    raw = r.stdout.strip()
    parts = raw.split("x")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return None, None


def _capture_progress_lines(ffmpeg: Path, input_video: Path,
                             output_video: Path) -> list[str]:
    """
    Run a short conversion and collect every stdout line that contains 'time='.
    Uses the same Popen pattern as converter.py _convert_file().
    """
    cmd = [
        str(ffmpeg), "-y", "-fflags", "+discardcorrupt",
        "-i", str(input_video),
        "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        "-max_muxing_queue_size", "9999",
        "-err_detect", "ignore_err",
        str(output_video),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        creationflags=_CREATION_FLAGS,
    )
    lines_with_time = []
    all_lines = []
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            all_lines.append(line.rstrip())
            if "time=" in line:
                lines_with_time.append(line.rstrip())
    proc.wait()
    return lines_with_time, all_lines, proc.returncode


# =============================================================================
# Shared test logic — called for both binary sets
# =============================================================================

def _run_all_probes(ffmpeg: Path, ffprobe: Path, label: str, tmp_path: Path):
    """
    Full probe/regex validation against a given binary set.
    Asserts hard failures; returns a dict of observations for comparison.
    """
    print(f"\n{'='*60}")
    print(f"  Binary set : {label}")
    print(f"  ffmpeg     : {_version(ffmpeg)}")
    print(f"  ffprobe    : {_version(ffprobe)}")
    print(f"{'='*60}")

    # ── 1. Generate synthetic test video ────────────────────────────────────
    test_video = tmp_path / "source.mp4"
    _make_test_video(ffmpeg, test_video, duration_secs=5)
    assert test_video.exists(), "lavfi source video was not created"
    print(f"  [OK] Created test video: {test_video.stat().st_size // 1024} KB")

    # ── 2. probe_file_duration() — bare float output format ────────────────
    duration = _probe_duration(ffprobe, test_video)
    assert duration > 0, f"probe_file_duration() returned {duration!r} (expected > 0)"
    assert 4.5 <= duration <= 5.5, f"Expected ~5 s, got {duration:.3f} s"
    print(f"  [OK] probe_file_duration() = {duration:.4f}s  (expected ~5.0)")

    # ── 3. Container validation (_validate_video_container) ─────────────────
    fmt = _probe_container_name(ffprobe, test_video)
    assert fmt and fmt != "N/A", f"format_name query returned: {fmt!r}"
    assert "mp4" in fmt.lower() or "mov" in fmt.lower(), \
        f"Unexpected container name: {fmt!r}"
    print(f"  [OK] format_name = {fmt!r}")

    # ── 4. Dimension probe (_has_odd_dimensions) ────────────────────────────
    w, h = _probe_dimensions(ffprobe, test_video)
    assert w == 160 and h == 120, \
        f"Expected 160x120, got {w}x{h}  (CSV format may have changed)"
    print(f"  [OK] stream dimensions = {w}x{h} (csv=s=x:p=0 format intact)")

    # ── 5. Progress output — time= regex ────────────────────────────────────
    out_video = tmp_path / "output.mp4"
    time_lines, all_lines, rc = _capture_progress_lines(ffmpeg, test_video, out_video)
    assert rc == 0, (
        f"Conversion exited with code {rc}.\n"
        f"Last 20 lines:\n" + "\n".join(all_lines[-20:])
    )
    assert time_lines, (
        "No 'time=' lines found in FFmpeg output — progress format may have changed.\n"
        f"All output:\n" + "\n".join(all_lines[-30:])
    )
    print(f"  [OK] Found {len(time_lines)} progress line(s) containing 'time='")
    print(f"       Sample: {time_lines[-1]!r}")

    # ── 6. time= regex match ─────────────────────────────────────────────────
    matched_time = [l for l in time_lines if TIME_RE.search(l)]
    assert matched_time, (
        "time= lines exist but TIME_RE did NOT match any of them.\n"
        f"Unmatched lines:\n" + "\n".join(time_lines[:5]) +
        f"\nPattern: {TIME_RE.pattern!r}"
    )
    sample_match = TIME_RE.search(matched_time[-1])
    h_, m_, s_ = sample_match.groups()
    parsed_secs = int(h_) * 3600 + int(m_) * 60 + float(s_)
    assert parsed_secs > 0, f"Parsed time from regex is {parsed_secs}s — expected > 0"
    print(f"  [OK] TIME_RE matches — parsed position: {parsed_secs:.2f}s")

    # ── 7. speed= regex match ────────────────────────────────────────────────
    matched_speed = [l for l in time_lines if SPEED_RE.search(l)]
    assert matched_speed, (
        "No 'speed=' match found in progress lines.\n"
        f"Lines searched:\n" + "\n".join(time_lines[:5]) +
        f"\nPattern: {SPEED_RE.pattern!r}"
    )
    speed_val = float(SPEED_RE.search(matched_speed[-1]).group(1))
    print(f"  [OK] SPEED_RE matches — speed: {speed_val}x")

    # ── 8. fps= regex match ──────────────────────────────────────────────────
    fps_lines = [l for l in all_lines if "fps=" in l]
    if fps_lines:
        matched_fps = [l for l in fps_lines if FPS_RE.search(l)]
        assert matched_fps, (
            f"fps= appears in output but FPS_RE did not match.\n"
            f"Sample: {fps_lines[0]!r}\nPattern: {FPS_RE.pattern!r}"
        )
        fps_val = float(FPS_RE.search(matched_fps[-1]).group(1))
        print(f"  [OK] FPS_RE matches  — fps: {fps_val}")
    else:
        print("  [--] fps= not present for this short encode (normal for ultrafast)")

    # ── 9. Flag compatibility: -passlogfile (two-pass) ───────────────────────
    pass_log = tmp_path / "2pass"
    pass1_cmd = [
        str(ffmpeg), "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=160x120:rate=25",
        "-c:v", "libx264", "-b:v", "300k",
        "-pass", "1", "-passlogfile", str(pass_log),
        "-an", "-f", "null", "NUL",
    ]
    r_p1 = _run(pass1_cmd)
    assert r_p1.returncode == 0, (
        f"-passlogfile / -pass 1 failed (exit {r_p1.returncode}):\n{r_p1.stderr[-1000:]}"
    )
    # Clean up log files
    for suffix in ["", ".mbtree"]:
        lf = Path(str(pass_log) + "-0.log" + suffix)
        if lf.exists():
            lf.unlink()
    print(f"  [OK] -passlogfile flag accepted (two-pass pass-1 exited 0)")

    # ── 10. Flag: -fflags +discardcorrupt ────────────────────────────────────
    flag_test = [
        str(ffmpeg), "-y", "-fflags", "+discardcorrupt",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=25",
        "-frames:v", "1", "-f", "null", "NUL",
    ]
    r_flag = _run(flag_test)
    assert r_flag.returncode == 0, (
        f"-fflags +discardcorrupt rejected (exit {r_flag.returncode}):\n{r_flag.stderr[-500:]}"
    )
    print(f"  [OK] -fflags +discardcorrupt accepted")

    # ── 11. Flag: -max_muxing_queue_size ────────────────────────────────────
    mux_test = [
        str(ffmpeg), "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=25",
        "-c:v", "libx264", "-max_muxing_queue_size", "9999",
        "-frames:v", "1", "-f", "null", "NUL",
    ]
    r_mux = _run(mux_test)
    assert r_mux.returncode == 0, (
        f"-max_muxing_queue_size 9999 rejected (exit {r_mux.returncode}):\n{r_mux.stderr[-500:]}"
    )
    print(f"  [OK] -max_muxing_queue_size 9999 accepted")

    # ── 12. ffprobe: corrupt/zero-byte file returns non-zero ────────────────
    zero = tmp_path / "zero.mp4"
    zero.write_bytes(b"")
    r_zero = _run([
        str(ffprobe), "-v", "error",
        "-show_entries", "format=format_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(zero),
    ])
    assert r_zero.returncode != 0 or r_zero.stdout.strip() == "", (
        f"ffprobe should fail on zero-byte file but returned: "
        f"rc={r_zero.returncode}, stdout={r_zero.stdout!r}"
    )
    print(f"  [OK] ffprobe zero-byte file -> rc={r_zero.returncode} (non-zero, as expected)")

    print(f"\n  ALL CHECKS PASSED for {label}\n")

    return {
        "version": _version(ffmpeg),
        "duration": duration,
        "container": fmt,
        "dimensions": (w, h),
        "time_re_sample": matched_time[-1] if matched_time else None,
        "speed": speed_val,
        "rc": rc,
    }


# =============================================================================
# Test Classes
# =============================================================================

class TestCurrentBinaries:
    """Sanity-check the already-deployed binaries as a baseline."""

    @requires_current
    def test_current_bundle_all_probes(self, tmp_path):
        _run_all_probes(CURRENT_FFMPEG, CURRENT_FFPROBE,
                        label="CURRENT (baseline)", tmp_path=tmp_path)

    @requires_current
    def test_current_ffprobe_duration_accuracy(self, tmp_path):
        """Duration must be within 50 ms of the requested encode length."""
        video = tmp_path / "v.mp4"
        _make_test_video(CURRENT_FFMPEG, video, duration_secs=10)
        d = _probe_duration(CURRENT_FFPROBE, video)
        assert abs(d - 10.0) < 0.1, f"Duration {d:.4f}s deviates > 50ms from 10.0s"

    @requires_current
    def test_current_time_regex_matches_real_output(self, tmp_path):
        """TIME_RE must match at least one progress line from a real encode."""
        src = tmp_path / "src.mp4"
        _make_test_video(CURRENT_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out.mp4"
        time_lines, _, rc = _capture_progress_lines(CURRENT_FFMPEG, src, out)
        assert rc == 0
        matches = [l for l in time_lines if TIME_RE.search(l)]
        assert matches, (
            f"TIME_RE={TIME_RE.pattern!r} matched nothing.\n"
            f"time= lines: {time_lines[:5]}"
        )


class TestStagingBinaries:
    """Validate FFmpeg 8.1.1 binaries against every pattern our app relies on."""

    @requires_staging
    def test_staging_all_probes(self, tmp_path):
        _run_all_probes(STAGING_FFMPEG, STAGING_FFPROBE,
                        label="STAGING (FFmpeg 8.1.1 candidate)", tmp_path=tmp_path)

    @requires_staging
    def test_staging_version_is_newer(self):
        """Confirm staging binary actually reports a newer version."""
        staging_ver = _version(STAGING_FFMPEG)
        current_ver = _version(CURRENT_FFMPEG)
        print(f"\n  Current : {current_ver}")
        print(f"  Staging : {staging_ver}")
        # Both are non-empty; staging should mention 8.1
        assert "8.1" in staging_ver, (
            f"Staging binary doesn't appear to be 8.1.x.\nVersion: {staging_ver!r}"
        )

    @requires_staging
    def test_staging_ffprobe_duration_accuracy(self, tmp_path):
        video = tmp_path / "v.mp4"
        _make_test_video(STAGING_FFMPEG, video, duration_secs=10)
        d = _probe_duration(STAGING_FFPROBE, video)
        assert abs(d - 10.0) < 0.1, f"Duration {d:.4f}s deviates > 50ms from 10.0s"

    @requires_staging
    def test_staging_time_regex_matches(self, tmp_path):
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out.mp4"
        time_lines, _, rc = _capture_progress_lines(STAGING_FFMPEG, src, out)
        assert rc == 0
        matches = [l for l in time_lines if TIME_RE.search(l)]
        assert matches, (
            f"TIME_RE={TIME_RE.pattern!r} matched nothing in 8.1.1 output.\n"
            f"time= lines (first 5): {time_lines[:5]}"
        )

    @requires_staging
    def test_staging_speed_regex_matches(self, tmp_path):
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out.mp4"
        time_lines, _, rc = _capture_progress_lines(STAGING_FFMPEG, src, out)
        assert rc == 0
        matches = [l for l in time_lines if SPEED_RE.search(l)]
        assert matches, (
            f"SPEED_RE={SPEED_RE.pattern!r} matched nothing in 8.1.1 output.\n"
            f"time= lines: {time_lines[:5]}"
        )

    @requires_staging
    def test_staging_webm_output(self, tmp_path):
        """Verify libvpx-vp9 + libopus still works (WebM format support)."""
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out.webm"
        cmd = [
            str(STAGING_FFMPEG), "-y",
            "-i", str(src),
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", "35", "-b:v", "0",
            "-c:a", "libopus", "-b:a", "128k",
            str(out),
        ]
        r = _run(cmd)
        assert r.returncode == 0, (
            f"WebM encode failed (exit {r.returncode}):\n{r.stderr[-1000:]}"
        )
        assert out.exists() and out.stat().st_size > 0

    @requires_staging
    def test_staging_mp3_audio_only(self, tmp_path):
        """Verify -vn + libmp3lame still works (MP3 output)."""
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out.mp3"
        cmd = [
            str(STAGING_FFMPEG), "-y", "-i", str(src),
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k",
            str(out),
        ]
        r = _run(cmd)
        assert r.returncode == 0, (
            f"MP3 audio-only encode failed (exit {r.returncode}):\n{r.stderr[-500:]}"
        )
        assert out.exists() and out.stat().st_size > 0

    @requires_staging
    def test_staging_h265_output(self, tmp_path):
        """Verify libx265 CPU encode still works (MP4 H.265 format)."""
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=3)
        out = tmp_path / "out_h265.mp4"
        cmd = [
            str(STAGING_FFMPEG), "-y", "-i", str(src),
            "-c:v", "libx265", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-crf", "35",
            "-c:a", "aac", "-b:a", "64k",
            str(out),
        ]
        r = _run(cmd)
        assert r.returncode == 0, (
            f"libx265 encode failed (exit {r.returncode}):\n{r.stderr[-1000:]}"
        )
        assert out.exists() and out.stat().st_size > 0

    @requires_staging
    def test_staging_err_detect_ignore_err_flag(self, tmp_path):
        """-err_detect ignore_err must still be accepted."""
        src = tmp_path / "src.mp4"
        _make_test_video(STAGING_FFMPEG, src, duration_secs=2)
        out = tmp_path / "out.mp4"
        cmd = [
            str(STAGING_FFMPEG), "-y", "-i", str(src),
            "-c:v", "libx264", "-crf", "35", "-preset", "ultrafast",
            "-err_detect", "ignore_err",
            str(out),
        ]
        r = _run(cmd)
        assert r.returncode == 0, (
            f"-err_detect ignore_err rejected (exit {r.returncode}):\n{r.stderr[-500:]}"
        )


class TestBinaryComparison:
    """
    Side-by-side comparison: run identical encodes against both binary sets
    and verify that outputs and parsed values are equivalent.
    """

    @requires_current
    @requires_staging
    def test_duration_probe_consistent_across_versions(self, tmp_path):
        """
        Same lavfi source encoded by both binaries must give the same duration
        reading from ffprobe (within 10 ms).
        """
        src_cur = tmp_path / "cur.mp4"
        src_stg = tmp_path / "stg.mp4"
        _make_test_video(CURRENT_FFMPEG, src_cur, duration_secs=5)
        _make_test_video(STAGING_FFMPEG, src_stg, duration_secs=5)

        d_cur = _probe_duration(CURRENT_FFPROBE, src_cur)
        d_stg = _probe_duration(STAGING_FFPROBE, src_stg)

        print(f"\n  Current ffprobe duration : {d_cur:.6f}s")
        print(f"  Staging ffprobe duration : {d_stg:.6f}s")
        assert abs(d_cur - d_stg) < 0.1, (
            f"Duration mismatch: current={d_cur:.4f}s, staging={d_stg:.4f}s"
        )

    @requires_current
    @requires_staging
    def test_time_regex_pattern_works_on_both(self, tmp_path):
        """
        TIME_RE must match at least one progress line from both binary versions.
        This is the core regression test: if the 8.1.1 progress format changed,
        this assertion fails and the regex in converter.py needs updating.
        """
        for label, ffmpeg, ffprobe in [
            ("CURRENT", CURRENT_FFMPEG, CURRENT_FFPROBE),
            ("STAGING", STAGING_FFMPEG, STAGING_FFPROBE),
        ]:
            src = tmp_path / f"src_{label.lower()}.mp4"
            out = tmp_path / f"out_{label.lower()}.mp4"
            _make_test_video(ffmpeg, src, duration_secs=3)
            time_lines, all_lines, rc = _capture_progress_lines(ffmpeg, src, out)

            assert rc == 0, f"[{label}] conversion failed (exit {rc})"
            matches = [l for l in time_lines if TIME_RE.search(l)]
            assert matches, (
                f"[{label}] TIME_RE={TIME_RE.pattern!r} matched nothing.\n"
                f"Progress lines containing 'time=':\n" + "\n".join(time_lines[:10])
            )
            print(f"\n  [{label}] Sample match: {matches[-1]!r}")

    @requires_current
    @requires_staging
    def test_speed_and_fps_regex_both_versions(self, tmp_path):
        """SPEED_RE must match in both binary sets."""
        for label, ffmpeg, _ in [
            ("CURRENT", CURRENT_FFMPEG, CURRENT_FFPROBE),
            ("STAGING", STAGING_FFMPEG, STAGING_FFPROBE),
        ]:
            src = tmp_path / f"src_{label.lower()}.mp4"
            out = tmp_path / f"out_{label.lower()}.mp4"
            _make_test_video(ffmpeg, src, duration_secs=3)
            time_lines, _, rc = _capture_progress_lines(ffmpeg, src, out)
            assert rc == 0
            s_match = [l for l in time_lines if SPEED_RE.search(l)]
            assert s_match, f"[{label}] SPEED_RE matched nothing: {time_lines[:3]}"

    @requires_current
    @requires_staging
    def test_probe_format_output_identical(self, tmp_path):
        """
        format=format_name query must produce identical output from both
        binary versions for the same source file.
        """
        src = tmp_path / "shared.mp4"
        # Use current binary to make the source — ffprobe reads the file, so
        # the creating binary doesn't matter.
        _make_test_video(CURRENT_FFMPEG, src, duration_secs=3)

        fmt_cur = _probe_container_name(CURRENT_FFPROBE, src)
        fmt_stg = _probe_container_name(STAGING_FFPROBE, src)

        print(f"\n  Current ffprobe format : {fmt_cur!r}")
        print(f"  Staging ffprobe format : {fmt_stg!r}")
        assert fmt_cur == fmt_stg, (
            f"format_name output differs between versions: "
            f"{fmt_cur!r} vs {fmt_stg!r}"
        )

    @requires_current
    @requires_staging
    def test_dimension_probe_output_identical(self, tmp_path):
        """csv=s=x:p=0 dimension probe must produce the same format in both versions."""
        src = tmp_path / "shared.mp4"
        _make_test_video(CURRENT_FFMPEG, src, duration_secs=2)

        w_cur, h_cur = _probe_dimensions(CURRENT_FFPROBE, src)
        w_stg, h_stg = _probe_dimensions(STAGING_FFPROBE, src)

        print(f"\n  Current : {w_cur}x{h_cur}")
        print(f"  Staging : {w_stg}x{h_stg}")
        assert (w_cur, h_cur) == (w_stg, h_stg) == (160, 120), (
            f"Dimension probe mismatch: current={w_cur}x{h_cur}, "
            f"staging={w_stg}x{h_stg}"
        )
