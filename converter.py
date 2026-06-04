import os
import subprocess
import threading
import re
import queue
import time
import logging
import sys
import shutil
import tempfile
import uuid

def get_binary_path(binary_name):
    """
    Returns the path to the binary (ffmpeg/ffprobe).
    Prioritizes:
    1. PyInstaller bundled path (_MEIPASS)
    2. Local 'bin' folder
    3. System PATH (fallback)
    """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    bin_path = os.path.join(base_path, 'bin', binary_name)
    if os.path.exists(bin_path):
        return bin_path

    return binary_name


def _get_audio_args(fmt):
    """Returns the correct audio codec arguments for the given output format."""
    if fmt == 'webm':
        return ['-c:a', 'libopus', '-b:a', '128k']
    elif fmt == 'avi':
        return ['-c:a', 'libmp3lame', '-b:a', '128k']
    elif fmt == 'mp3':
        return ['-vn', '-c:a', 'libmp3lame', '-b:a', '192k']
    else:
        return ['-c:a', 'aac', '-b:a', '128k']


class ConversionManager:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("VideoConverter")
        self.queue = queue.Queue()
        self.active = False
        self.threads = []
        self.active_processes = {}
        self.process_lock = threading.Lock()
        self.worker_start_event = threading.Event()
        self.current_positions = {}   # input_file → current encoded seconds (live)

    def add_task(self, input_file, output_file, format_settings, progress_callback=None, status_callback=None, completion_callback=None):
        """Adds a conversion task to the queue."""
        task = {
            'input': input_file,
            'output': output_file,
            'settings': format_settings,
            'progress_callback': progress_callback,
            'status_callback': status_callback,
            'completion_callback': completion_callback
        }
        self.queue.put(task)

    def start_processing(self, max_workers=1):
        """Starts the background worker threads with a stagger to prevent resource spikes."""
        if self.active:
            return

        self.active = True
        self.threads = []

        spawner = threading.Thread(target=self._spawn_workers_staggered, args=(max_workers,), daemon=True)
        spawner.start()

    def _spawn_workers_staggered(self, count):
        """Spawns worker threads with an event-driven stagger delay."""
        for i in range(count):
            if not self.active:
                break

            t = threading.Thread(target=self._worker, args=(count,), daemon=True)
            t.start()
            self.threads.append(t)

            if i < count - 1:
                self.worker_start_event.clear()
                self.worker_start_event.wait(timeout=5.0)

    def stop_processing(self):
        """Stops the current conversion and clears queue, terminating all active subprocesses."""
        self.active = False

        with self.queue.mutex:
            self.queue.queue.clear()

        with self.process_lock:
            for input_file, process in list(self.active_processes.items()):
                try:
                    self.logger.info(f"Forcibly terminating active conversion: {input_file}")
                    if process.poll() is None:
                        process.terminate()
                except Exception as e:
                    self.logger.error(f"Error terminating process for {input_file}: {e}")
            self.active_processes.clear()

    def _worker(self, max_workers):
        """Main worker loop."""
        while self.active:
            try:
                try:
                    task = self.queue.get(timeout=1)
                except queue.Empty:
                    continue

                input_file = task['input']
                output_file = task['output']
                settings = task['settings']
                progress_cb = task.get('progress_callback')
                status_cb = task.get('status_callback')
                completion_cb = task.get('completion_callback')

                self.logger.info(f"Starting conversion: {input_file} -> {output_file}")

                if not os.path.exists(input_file) or not os.access(input_file, os.R_OK):
                    self.queue.task_done()
                    if completion_cb:
                        completion_cb(input_file, "Unreadable Input File", False)
                    continue

                if not self._validate_video_container(input_file):
                    self.queue.task_done()
                    if completion_cb:
                        completion_cb(input_file, "Invalid Video Format", False)
                    continue

                file_size = os.path.getsize(input_file)
                reduction = settings.get('compress_percentage', 0) / 100.0
                estimated_size = file_size * (1 - reduction) if reduction > 0 else file_size * 1.2

                output_dir = os.path.dirname(output_file)
                if output_dir:
                    try:
                        os.makedirs(output_dir, exist_ok=True)
                    except OSError as e:
                        self.logger.error(f"Cannot create output directory: {e}")
                        self.queue.task_done()
                        if completion_cb:
                            completion_cb(input_file, f"Permission Denied: {e}", False)
                        continue
                else:
                    output_dir = '.'

                try:
                    total, used, free = shutil.disk_usage(output_dir)
                    if free < estimated_size:
                        self.queue.task_done()
                        if completion_cb:
                            completion_cb(input_file, "Insufficient Disk Space", False)
                        continue
                except Exception as e:
                    self.logger.warning(f"Disk space check failed: {e}")

                duration = self._get_duration(input_file)

                success, error_msg = self._convert_file(input_file, output_file, settings, duration, progress_cb, max_workers)

                # Fallback to CPU on GPU failure
                if not success and settings.get('acceleration', 'CPU') != 'CPU':
                    self.logger.warning(f"GPU conversion failed for {input_file}: {error_msg}. Retrying with CPU...")
                    if status_cb:
                        status_cb("Retrying with CPU...", "primary")

                    cpu_settings = settings.copy()
                    cpu_settings['acceleration'] = 'CPU'

                    success, error_msg = self._convert_file(input_file, output_file, cpu_settings, duration, progress_cb, max_workers)

                self.queue.task_done()

                if completion_cb:
                    if not self.active:
                        completion_cb(input_file, "Cancelled", False)
                    elif success:
                        completion_cb(input_file, output_file, True)
                    else:
                        msg = error_msg if error_msg else "Failed"
                        completion_cb(input_file, msg, False)

            except Exception as e:
                self.logger.error(f"Worker error: {e}", exc_info=True)

    def _validate_video_container(self, input_file):
        """Validates video/audio format using ffprobe."""
        try:
            ffprobe_cmd = get_binary_path('ffprobe.exe')
            cmd = [
                ffprobe_cmd, '-v', 'error',
                '-show_entries', 'format=format_name',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                input_file
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0 and len(result.stdout.strip()) > 0
        except Exception as e:
            self.logger.error(f"Container validation error: {e}")
            return False

    def probe_file_duration(self, path):
        """Return the actual encoded duration of a (possibly partial) file in seconds."""
        try:
            ffprobe_cmd = get_binary_path('ffprobe.exe')
            cmd = [ffprobe_cmd, '-v', 'error',
                   '-show_entries', 'format=duration',
                   '-of', 'default=noprint_wrappers=1:nokey=1', path]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            val = r.stdout.strip()
            if val and val != 'N/A':
                return float(val)
        except Exception:
            pass
        return 0.0

    def remux_to_output(self, src_mkv, dst_path, fmt):
        """
        Fast stream-copy from the temp MKV intermediate to the final container.
        No re-encoding — typically completes in under a second.
        """
        ffmpeg_cmd = get_binary_path('ffmpeg.exe')
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmd = [ffmpeg_cmd, '-y', '-i', src_mkv, '-c', 'copy']
        if fmt == 'mp4' or fmt == 'mp4 (h.265)' or fmt == 'mov':
            cmd += ['-movflags', '+faststart']
        cmd.append(dst_path)
        self.logger.info(f"Remux: {' '.join(cmd)}")
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120,
                               creationflags=creation_flags)
            return r.returncode == 0
        except Exception as e:
            self.logger.error(f"Remux failed: {e}")
            return False

    def concat_and_remux(self, part1_mkv, part2_mkv, dst_path, fmt):
        """
        Concatenate two temp MKV segments and remux to the final container.
        Uses the concat demuxer so no re-encoding is needed.
        """
        ffmpeg_cmd = get_binary_path('ffmpeg.exe')
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        def _ffconcat_escape(p):
            # FFmpeg concat demuxer: use forward slashes, escape single quotes.
            return p.replace('\\', '/').replace("'", "\\'")

        # Write a temp concat list
        list_path = part1_mkv + '_concat_list.txt'
        try:
            with open(list_path, 'w', encoding='utf-8') as f:
                f.write(f"file '{_ffconcat_escape(part1_mkv)}'\n")
                f.write(f"file '{_ffconcat_escape(part2_mkv)}'\n")

            cmd = [ffmpeg_cmd, '-y', '-f', 'concat', '-safe', '0',
                   '-i', list_path, '-c', 'copy']
            if fmt == 'mp4' or fmt == 'mp4 (h.265)' or fmt == 'mov':
                cmd += ['-movflags', '+faststart']
            cmd.append(dst_path)
            self.logger.info(f"Concat+remux: {' '.join(cmd)}")
            r = subprocess.run(cmd, capture_output=True, timeout=300,
                               creationflags=creation_flags)
            return r.returncode == 0
        except Exception as e:
            self.logger.error(f"Concat failed: {e}")
            return False
        finally:
            try:
                os.remove(list_path)
            except Exception:
                pass

    def _has_odd_dimensions(self, input_file):
        """Returns True if the video stream has an odd width or height."""
        try:
            ffprobe_cmd = get_binary_path('ffprobe.exe')
            cmd = [
                ffprobe_cmd, '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=s=x:p=0',
                input_file
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('x')
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    return (w % 2 != 0) or (h % 2 != 0)
        except Exception:
            pass
        return False

    def _get_duration(self, input_file):
        """Gets video/audio duration using ffprobe."""
        try:
            ffprobe_cmd = get_binary_path('ffprobe.exe')
            cmd = [
                ffprobe_cmd, '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                input_file
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            val = result.stdout.strip()
            if val and val != 'N/A':
                return float(val)
            return 0.0
        except Exception as e:
            self.logger.warning(f"Could not get duration for {input_file}: {e}")
            return 0.0

    def _convert_file(self, input_file, output_file, settings, total_duration, progress_callback, max_workers=1):
        """Executes ffmpeg command (supporting optional trim and two-pass compression) and monitors progress."""
        ffmpeg_cmd = get_binary_path('ffmpeg.exe')
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        accel = settings.get('acceleration', 'CPU')
        if accel == 'CPU':
            threads_count = max(1, os.cpu_count() // max_workers)
        else:
            threads_count = 1

        quality = settings.get('quality', 'High')
        crf_map = {"Ultra": 18, "High": 23, "Balanced": 28, "Fast": 35}
        crf = crf_map.get(quality, 23)

        start_time_str = settings.get('start_time', '')
        end_time_str = settings.get('end_time', '')
        trim_args = []
        if start_time_str:
            trim_args.extend(['-ss', start_time_str])
        if end_time_str:
            trim_args.extend(['-to', end_time_str])

        fmt = settings.get('format', 'mp4')
        audio_args = _get_audio_args(fmt)

        # Compression Mode (Two-Pass libx264) — only for h264-compatible containers
        # webm needs vp9 two-pass (different flow), mp4 (h.265) needs x265, mp3 is audio-only
        TWO_PASS_FORMATS = {'mp4', 'mkv', 'avi', 'mov'}
        compress_percentage = settings.get('compress_percentage', 0)
        if compress_percentage > 0 and total_duration > 0 and fmt in TWO_PASS_FORMATS:
            # Calculate target bitrate
            file_size = os.path.getsize(input_file)
            target_size_bytes = file_size * (1 - compress_percentage / 100.0)
            target_size_bits = target_size_bytes * 8
            audio_bitrate_bps = 128000
            video_bitrate = int((target_size_bits / total_duration) - audio_bitrate_bps)
            if video_bitrate < 150000:
                video_bitrate = 150000

            pass_log_prefix = os.path.join(tempfile.gettempdir(), f"2pass_{uuid.uuid4().hex}")

            # PASS 1 Command
            pass1_cmd = [ffmpeg_cmd, '-y', '-fflags', '+discardcorrupt']
            if trim_args:
                pass1_cmd.extend(trim_args)
            pass1_cmd.extend(['-threads', str(threads_count), '-i', input_file])
            pass1_cmd.extend([
                '-c:v', 'libx264', '-b:v', str(video_bitrate),
                '-pass', '1', '-passlogfile', pass_log_prefix,
                '-an', '-f', 'null', 'NUL'
            ])

            self.logger.info(f"Pass 1: {' '.join(pass1_cmd)}")
            process1 = None
            try:
                process1 = subprocess.Popen(
                    pass1_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=creation_flags
                )

                with self.process_lock:
                    self.active_processes[input_file] = process1

                time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
                while True:
                    if not self.active:
                        process1.terminate()
                        return False, "Cancelled"
                    line = process1.stdout.readline()
                    if not line and process1.poll() is not None:
                        break
                    if line:
                        self.worker_start_event.set()
                        match_time = time_pattern.search(line)
                        if match_time and progress_callback:
                            h, m, s = map(float, match_time.groups())
                            cur_sec = h * 3600 + m * 60 + s
                            percent = min(100.0, (cur_sec / total_duration) * 100)
                            progress_callback(percent * 0.45, 0.0, 1.0, 0.0)

                if process1.returncode != 0:
                    for suffix in ['', '.mbtree']:
                        log_f = f"{pass_log_prefix}-0.log{suffix}"
                        if os.path.exists(log_f):
                            try:
                                os.remove(log_f)
                            except Exception:
                                pass
                    return False, "Compression Pass 1 Failed"
            except Exception as e:
                self.worker_start_event.set()
                if process1:
                    try:
                        process1.terminate()
                    except Exception:
                        pass
                for suffix in ['', '.mbtree']:
                    log_f = f"{pass_log_prefix}-0.log{suffix}"
                    if os.path.exists(log_f):
                        try:
                            os.remove(log_f)
                        except Exception:
                            pass
                return False, f"Pass 1 Exception: {e}"
            finally:
                with self.process_lock:
                    if input_file in self.active_processes:
                        del self.active_processes[input_file]

            # PASS 2 Command
            pass2_cmd = [ffmpeg_cmd, '-y', '-fflags', '+discardcorrupt']
            if trim_args:
                pass2_cmd.extend(trim_args)
            pass2_cmd.extend(['-threads', str(threads_count), '-i', input_file])
            pass2_cmd.extend([
                '-c:v', 'libx264', '-b:v', str(video_bitrate),
                '-pass', '2', '-passlogfile', pass_log_prefix
            ])
            pass2_cmd.extend(audio_args)
            pass2_cmd.append(output_file)

            self.logger.info(f"Pass 2: {' '.join(pass2_cmd)}")
            process2 = None
            try:
                process2 = subprocess.Popen(
                    pass2_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=creation_flags
                )

                with self.process_lock:
                    self.active_processes[input_file] = process2

                time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
                speed_pattern = re.compile(r"speed=\s*(\d+(?:\.\d+)?)x")
                fps_pattern = re.compile(r"fps=\s*(\d+(?:\.\d+)?)")

                start_pass2 = time.time()
                while True:
                    if not self.active:
                        process2.terminate()
                        return False, "Cancelled"
                    line = process2.stdout.readline()
                    if not line and process2.poll() is not None:
                        break
                    if line:
                        match_time = time_pattern.search(line)
                        match_speed = speed_pattern.search(line)
                        match_fps = fps_pattern.search(line)

                        speed_val = 1.0
                        if match_speed:
                            try:
                                speed_val = float(match_speed.group(1))
                            except Exception:
                                pass
                        fps_val = 0.0
                        if match_fps:
                            try:
                                fps_val = float(match_fps.group(1))
                            except Exception:
                                pass

                        if match_time and progress_callback:
                            h, m, s = map(float, match_time.groups())
                            cur_sec = h * 3600 + m * 60 + s
                            percent = min(100.0, (cur_sec / total_duration) * 100)
                            scaled_percent = 45.0 + (percent * 0.55)

                            remaining_seconds = total_duration - cur_sec
                            eta_seconds = 0.0
                            if speed_val > 0:
                                eta_seconds = remaining_seconds / speed_val
                            else:
                                elapsed = time.time() - start_pass2
                                if cur_sec > 0:
                                    eta_seconds = remaining_seconds * (elapsed / cur_sec)

                            progress_callback(scaled_percent, eta_seconds, speed_val, fps_val)

                if process2.returncode != 0:
                    return False, "Compression Pass 2 Failed"
                return True, None
            except Exception as e:
                if process2:
                    try:
                        process2.terminate()
                    except Exception:
                        pass
                return False, f"Pass 2 Exception: {e}"
            finally:
                with self.process_lock:
                    if input_file in self.active_processes:
                        del self.active_processes[input_file]
                for suffix in ['', '.mbtree']:
                    log_f = f"{pass_log_prefix}-0.log" + suffix
                    if os.path.exists(log_f):
                        try:
                            os.remove(log_f)
                        except Exception:
                            pass

        # Standard One-Pass Encoding
        # Note: -hwaccel auto is intentionally omitted — hardware-decoded frames
        # arrive as nv12 which software encoders (libx264/libx265/libvpx) cannot
        # accept without an explicit pixel-format conversion, causing a crash.
        # GPU encoders handle their own decode pipeline internally.
        resume_from_secs = float(settings.get('resume_from_secs', 0))

        cmd = [ffmpeg_cmd, '-y', '-fflags', '+discardcorrupt']
        if trim_args:
            cmd.extend(trim_args)
        # Seek on the input side (fast, keyframe-accurate) for resume
        if resume_from_secs > 0:
            cmd.extend(['-ss', str(resume_from_secs)])

        if accel == 'CPU':
            cmd.extend(['-threads', str(threads_count)])
        else:
            cmd.extend(['-threads', '1'])

        cmd.extend(['-i', input_file])

        # Only add the even-dimension scale filter when actually needed.
        # libx264/libx265/libvpx-vp9 require width and height divisible by 2;
        # applying it unconditionally can crash decoders that produce non-standard
        # pixel formats (e.g. libaom-av1 → swscale interaction).
        needs_even_scale = fmt != 'mp3' and self._has_odd_dimensions(input_file)
        even_scale = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'

        if fmt != 'mp3':
            if fmt == 'webm':
                if needs_even_scale:
                    cmd.extend(['-vf', even_scale])
                if accel == 'NVIDIA (NVENC)':
                    cmd.extend(['-c:v', 'vp9_nvenc', '-pix_fmt', 'yuv420p', '-cq', str(crf)])
                else:
                    cmd.extend(['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p', '-crf', str(crf), '-b:v', '0'])
            elif fmt == 'mp4 (h.265)':
                if needs_even_scale:
                    cmd.extend(['-vf', even_scale])
                if accel == 'NVIDIA (NVENC)':
                    cmd.extend(['-c:v', 'hevc_nvenc', '-pix_fmt', 'yuv420p', '-preset', 'p4', '-rc', 'vbr_hq', '-cq', str(crf)])
                elif accel == 'Intel (QSV)':
                    cmd.extend(['-c:v', 'hevc_qsv', '-global_quality', str(crf)])
                elif accel == 'AMD (AMF)':
                    cmd.extend(['-c:v', 'hevc_amf', '-usage', 'transcoding', '-rc', 'cqp', '-qp_i', str(crf), '-qp_p', str(crf)])
                else:
                    cmd.extend(['-c:v', 'libx265', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', str(crf)])
            else:
                # H.264 for mp4, mkv, avi, mov
                if needs_even_scale:
                    cmd.extend(['-vf', even_scale])
                if accel == 'NVIDIA (NVENC)':
                    cmd.extend(['-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p', '-preset', 'p4', '-rc', 'vbr_hq', '-cq', str(crf)])
                elif accel == 'Intel (QSV)':
                    cmd.extend(['-c:v', 'h264_qsv', '-global_quality', str(crf), '-look_ahead', '1'])
                elif accel == 'AMD (AMF)':
                    cmd.extend(['-c:v', 'h264_amf', '-usage', 'transcoding', '-rc', 'cqp', '-qp_i', str(crf), '-qp_p', str(crf)])
                else:
                    cmd.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', str(crf)])

        cmd.extend(audio_args)

        if fmt != 'mp3':
            cmd.extend(['-err_detect', 'ignore_err'])
            cmd.extend(['-max_muxing_queue_size', '9999'])

        cmd.append(output_file)

        self.logger.info(f"Command: {' '.join(cmd)}")

        process = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=creation_flags
            )

            with self.process_lock:
                self.active_processes[input_file] = process

            time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
            speed_pattern = re.compile(r"speed=\s*(\d+(?:\.\d+)?)x")
            fps_pattern = re.compile(r"fps=\s*(\d+(?:\.\d+)?)")

            output_buffer = []
            encode_start = time.time()

            while True:
                if not self.active:
                    process.terminate()
                    return False, "Cancelled"

                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break

                if line:
                    self.worker_start_event.set()
                    output_buffer.append(line.strip())
                    if len(output_buffer) > 20:
                        output_buffer.pop(0)

                    match_time = time_pattern.search(line)
                    match_speed = speed_pattern.search(line)
                    match_fps = fps_pattern.search(line)

                    speed_val = 1.0
                    if match_speed:
                        try:
                            speed_val = float(match_speed.group(1))
                        except Exception:
                            pass

                    fps_val = 0.0
                    if match_fps:
                        try:
                            fps_val = float(match_fps.group(1))
                        except Exception:
                            pass

                    if match_time and total_duration > 0 and progress_callback:
                        h, m, s = map(float, match_time.groups())
                        current_seconds = h * 3600 + m * 60 + s
                        # Store live absolute position so pause can read it
                        self.current_positions[input_file] = resume_from_secs + current_seconds
                        # Progress relative to the segment being encoded, not full video.
                        # For resumed encodes, ffmpeg reports time=0…(remaining_duration).
                        effective_duration = total_duration - resume_from_secs
                        if effective_duration > 0:
                            percent = min(100.0, (current_seconds / effective_duration) * 100)
                        else:
                            percent = 100.0

                        remaining_seconds = total_duration - current_seconds
                        eta_seconds = 0.0
                        if speed_val > 0:
                            eta_seconds = remaining_seconds / speed_val
                        else:
                            elapsed = time.time() - encode_start
                            if current_seconds > 0:
                                eta_seconds = remaining_seconds * (elapsed / current_seconds)

                        progress_callback(percent, eta_seconds, speed_val, fps_val)

            self.worker_start_event.set()

            if process.returncode == 0:
                return True, None
            else:
                self.logger.error(f"FFmpeg exited with error code {process.returncode}")

                # Normalize to signed int for portable comparisons
                rc = process.returncode
                if rc > 2**31:
                    rc = rc - 2**32

                error_msg = "Failed"
                full_log = "\n".join(output_buffer)

                if rc in (-1073741819, -1073741571):  # 0xC0000005 / 0xC00000FD — access violation / stack overflow
                    error_msg = "Corrupt/Incomplete File (ffmpeg crash)"
                elif "does not contain any stream" in full_log or "Output file does not contain any stream" in full_log:
                    error_msg = "No audio stream in source file"
                elif "Unknown encoder" in full_log:
                    error_msg = "Unsupported GPU/Encoder"
                elif "DLL amfrt64.dll failed" in full_log:
                    error_msg = "AMD Driver Missing/Unsupported"
                elif "Error while opening encoder" in full_log:
                    error_msg = "Encoder Init Failed"
                elif "Permission denied" in full_log:
                    error_msg = "Permission Denied"
                elif "No such file" in full_log:
                    error_msg = "Missing Input"
                elif "Invalid data" in full_log or "moov atom not found" in full_log:
                    error_msg = "Corrupt/Incomplete File"
                elif "not supported" in full_log.lower() or "codec not currently supported" in full_log.lower():
                    error_msg = "Codec Not Supported"

                self.logger.error("Last 20 lines of FFmpeg output:")
                for ln in output_buffer:
                    self.logger.error(ln)

                return False, error_msg

        except Exception as e:
            self.worker_start_event.set()
            self.logger.error(f"Conversion Failed: {e}", exc_info=True)
            if process:
                try:
                    process.terminate()
                except Exception:
                    pass
            return False, str(e)
        finally:
            with self.process_lock:
                if input_file in self.active_processes:
                    del self.active_processes[input_file]
            self.current_positions.pop(input_file, None)
