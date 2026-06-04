/**
 * Production app.jsx — all file operations go through window.pywebview.api.
 * Receives real-time updates from Python via 'vc-update' CustomEvents.
 */
const { useState, useEffect, useRef, useCallback } = React;
const { fmtColor, OUTPUT_FORMATS, QUALITY_PRESETS, GPU_OPTIONS, PARALLEL_OPTIONS, labelOf } = window.VCData;

let _nextId = 1;
const uid = () => _nextId++;

/* ── Helpers ── */
const fmtTime = (s) => {
  const m = Math.floor(s / 60), sec = s % 60;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
};

function App() {
  const [files,   setFiles]   = useState([]);
  const [target,  setTarget]  = useState("mp4");
  const [preset,  setPreset]  = useState("High");
  const [gpu,     setGpu]     = useState("CPU");
  const [parallel,setParallel]= useState("1");
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [rules,   setRules]   = useState({ keep: false, del: false });
  const [modal,   setModal]   = useState(null);   // 'about' | 'history'
  const [apiReady, setApiReady] = useState(false);

  const timerRef  = useRef(null);
  const trimsRef  = useRef({});   // fileId → {start, end}

  /* ── Wait for pywebview API ── */
  useEffect(() => {
    const onReady = () => setApiReady(true);
    // pywebview fires 'pywebviewready' when window.pywebview.api is mounted.
    // Also check synchronously in case it fired before this effect ran.
    window.addEventListener("pywebviewready", onReady);
    if (window.pywebview?.api) setApiReady(true);
    return () => window.removeEventListener("pywebviewready", onReady);
  }, []);

  /* ── Real-time update listener (progress/done/error from Python) ── */
  useEffect(() => {
    const handler = (e) => {
      const data = typeof e.detail === "string" ? JSON.parse(e.detail) : e.detail;
      if (!data) return;

      if (data.type === "duration") {
        // Background ffprobe result — update file by path
        setFiles((fs) => fs.map((f) =>
          f.path === data.path ? { ...f, duration: data.duration } : f
        ));
      } else if (data.type === "paused") {
        // File was paused mid-conversion — store paused_at so UI shows position
        setFiles((fs) => fs.map((f) =>
          f.id === data.id
            ? { ...f, status: "paused", progress: f.progress, paused_at: data.paused_at || 0 }
            : f
        ));
      } else if (data.type === "resumed") {
        // Backend confirmed resume — switch back to converting
        setFiles((fs) => fs.map((f) =>
          f.id === data.id
            ? { ...f, status: "converting", progress: data.progress || f.progress, paused_at: undefined }
            : f
        ));
      } else if (data.type === "progress") {
        setFiles((fs) => fs.map((f) =>
          f.id === data.id ? { ...f, status: "converting", progress: data.progress } : f
        ));
      } else if (data.type === "done") {
        setFiles((fs) => fs.map((f) =>
          f.id === data.id
            ? { ...f, status: "done", progress: 100,
                output_path: data.output_path, size: data.output_size || f.size }
            : f
        ));
      } else if (data.type === "error") {
        setFiles((fs) => fs.map((f) =>
          f.id === data.id ? { ...f, status: "error", error: data.error } : f
        ));
      } else if (data.type === "queue_done") {
        setRunning(false);
        clearInterval(timerRef.current);
      }
    };
    window.addEventListener("vc-update", handler);
    return () => window.removeEventListener("vc-update", handler);
  }, []);

  /* ── Elapsed timer ── */
  useEffect(() => {
    if (running) {
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [running]);

  /* ── Derived stats ── */
  const total   = files.length;
  const done    = files.filter((f) => f.status === "done").length;
  const overall = total === 0 ? 0
    : files.reduce((a, f) => a + (
        f.status === "done"       ? 100 :
        f.status === "converting" ? f.progress :
        f.status === "paused"     ? f.progress :
        f.status === "error"      ? 100 : 0), 0) / total;

  /* ── File operations ── */
  const addFiles = useCallback(async () => {
    if (!apiReady) return;
    const result = await window.pywebview.api.add_files();
    if (!result || !result.length) return;
    setFiles((fs) => {
      const existing = new Set(fs.map((f) => f.path));
      const fresh = result
        .filter((r) => !existing.has(r.path))
        .map((r) => ({ ...r, id: uid() }));
      return [...fs, ...fresh];
    });
  }, [apiReady]);

  const addFolder = useCallback(async () => {
    if (!apiReady) return;
    const result = await window.pywebview.api.add_folder();
    if (!result || !result.length) return;
    setFiles((fs) => {
      const existing = new Set(fs.map((f) => f.path));
      const fresh = result
        .filter((r) => !existing.has(r.path))
        .map((r) => ({ ...r, id: uid() }));
      return [...fs, ...fresh];
    });
  }, [apiReady]);

  const pauseFile = useCallback((id) => {
    if (!apiReady) return;
    window.pywebview.api.pause_file(id);
  }, [apiReady]);

  const resumeFile = useCallback((id) => {
    if (!apiReady) return;
    window.pywebview.api.resume_file(id);
    setRunning(true);
  }, [apiReady]);

  const removeFile = (id) => {
    setFiles((fs) => fs.filter((f) => f.id !== id));
    delete trimsRef.current[id];
  };

  const clearQueue = () => {
    if (running) window.pywebview?.api?.pause_conversion?.();
    setFiles([]);
    setRunning(false);
    setElapsed(0);
    trimsRef.current = {};
    clearInterval(timerRef.current);
    // Clear any paused states in the backend too
    window.pywebview?.api?.clear_paused_states?.();
  };

  const openOutputFolder = (path) => {
    window.pywebview?.api?.open_output_folder?.(path);
  };

  /* ── Conversion ── */
  const toggleRun = async () => {
    if (running) {
      await window.pywebview?.api?.pause_conversion?.();
      setRunning(false);
      clearInterval(timerRef.current);
      return;
    }

    // Resume any paused files first
    const paused = files.filter((f) => f.status === "paused");
    for (const f of paused) {
      window.pywebview?.api?.resume_file?.(f.id);
    }

    const queued = files.filter((f) => f.status === "queue");
    if (!queued.length && !paused.length) return;

    // Mark all queued as still-queued (reset any previous errors if retrying)
    setFiles((fs) => fs.map((f) =>
      f.status === "queue" ? { ...f, progress: 0 } : f
    ));

    setElapsed(0);
    setRunning(true);

    const payload = queued.map((f) => ({
      id:       f.id,
      path:     f.path,
      name:     f.name,
      ext:      f.ext,
      duration: f.duration || 0,
      trim:     trimsRef.current[f.id] || null,
    }));

    const settings = {
      format:          target,
      quality:         preset,
      gpu:             gpu,
      parallel:        parallel,
      keep_dir:        rules.keep,
      delete_original: rules.del,
      name_template:   "{name}_converted",
    };

    await window.pywebview?.api?.start_conversion?.(payload, settings);
  };

  const handleTrimApply = (fileId, start, end) => {
    trimsRef.current[fileId] = { start, end };
  };

  /* ── Render ── */
  const pausedCount = files.filter((f) => f.status === "paused").length;
  const bbLabel = running
    ? `Converting ${total} file${total !== 1 ? "s" : ""}…`
    : pausedCount > 0
      ? `${pausedCount} file${pausedCount !== 1 ? "s" : ""} paused — click Resume`
      : done === total && total > 0
        ? "All conversions complete"
        : "Ready to convert";
  const bbButtonLabel = running ? "Pause" : pausedCount > 0 ? "Resume" : "Start Conversion";

  return (
    <div className="win">
      <TitleBar />
      <div className="body">
        <Sidebar
          onAddFiles={addFiles}
          onAddFolder={addFolder}
          onOpenHistory={() => setModal("history")}
          onOpenAbout={() => setModal("about")}
          onOpenLogs={() => window.pywebview?.api?.open_logs_folder?.()}
          rules={rules}
          setRules={setRules}
        />

        <main className="content">
          <div className="chead">
            <div className="chead-row">
              <div>
                <h1>Conversion Queue</h1>
                <div className="chead-sub">
                  {total > 0
                    ? <><b>{total}</b> file{total !== 1 ? "s" : ""} · {labelOf(OUTPUT_FORMATS, target)} · {labelOf(QUALITY_PRESETS, preset)} quality · {labelOf(GPU_OPTIONS, gpu)} engine</>
                    : "No files in the queue yet"}
                </div>
              </div>
            </div>

            {total > 0 && (
              <div className="setbar">
                <div className="ctrl">
                  <span className="ctrl-l">Output Format</span>
                  <Dropdown value={target} options={OUTPUT_FORMATS} onChange={setTarget} renderDot={fmtColor} />
                </div>
                <div className="tb-sep" />
                <div className="ctrl">
                  <span className="ctrl-l">Quality Preset</span>
                  <Dropdown value={preset} options={QUALITY_PRESETS} onChange={setPreset} />
                </div>
                <div className="tb-sep" />
                <div className="ctrl">
                  <span className="ctrl-l">GPU Acceleration</span>
                  <Dropdown value={gpu} options={GPU_OPTIONS} onChange={setGpu} />
                </div>
                <div className="tb-sep" />
                <div className="ctrl">
                  <span className="ctrl-l">Parallel Conversions</span>
                  <Dropdown value={parallel} options={PARALLEL_OPTIONS} onChange={setParallel} />
                </div>
                <div className="setbar-spacer" />
                <button className="link-danger" onClick={clearQueue}><Icons.x size={15} /> Clear Queue</button>
              </div>
            )}
          </div>

          {total === 0 ? (
            <EmptyState onAdd={addFiles} onAddFolder={addFolder} />
          ) : (
            <div className="queue-scroll">
              <div className="qlist">
                {files.map((f) => (
                  <FileRow
                    key={f.id}
                    file={f}
                    target={target}
                    onRemove={removeFile}
                    onOpenFolder={openOutputFolder}
                    onTrimApply={handleTrimApply}
                    onPause={pauseFile}
                    onResume={resumeFile}
                  />
                ))}
              </div>
            </div>
          )}

          <BottomBar
            files={files}
            running={running}
            elapsed={elapsed}
            overall={overall}
            label={bbLabel}
            buttonLabel={bbButtonLabel}
            onToggleRun={toggleRun}
          />

        </main>
      </div>

      {modal === "about"   && <AboutModal   onClose={() => setModal(null)} />}
      {modal === "history" && <HistoryModal onClose={() => setModal(null)} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
