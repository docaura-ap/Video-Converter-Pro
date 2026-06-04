const { fmtColor: rowFmtColor } = window.VCData;

const STATUS_META = {
  done:       { cls: "done",   label: "Done" },
  converting: { cls: "run",    label: "Converting" },
  queue:      { cls: "queue",  label: "Queued" },
  error:      { cls: "err",    label: "Failed" },
  paused:     { cls: "paused", label: "Paused" },
};

function StatusPill({ status }) {
  const m = STATUS_META[status] || STATUS_META.queue;
  if (status === "converting")
    return <span className="pill run"><Icons.loader size={13} className="spin" /> {m.label}</span>;
  if (status === "done")
    return <span className="pill done"><span className="dot" /> {m.label}</span>;
  if (status === "queue")
    return <span className="pill queue"><span className="dot" /> {m.label}</span>;
  if (status === "paused")
    return <span className="pill paused"><span className="dot" /> {m.label}</span>;
  return <span className="pill err"><span className="dot" /> {m.label}</span>;
}

const hmsShort = (sec) => {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
};

function FileRow({ file, target, onRemove, onOpenFolder, onTrimApply, onPause, onResume }) {
  const { id, name, ext, src, size, status, path, progress, error, output_path, paused_at } = file;
  const [trimOpen, setTrimOpen]   = React.useState(false);
  const [savedTrim, setSavedTrim] = React.useState(null);

  const rowCls      = "row fade-in" +
    (status === "converting" ? " is-run" : status === "error" ? " is-err" : status === "paused" ? " is-paused" : "");
  const targetLabel = window.VCData.labelOf(window.VCData.OUTPUT_FORMATS, target);
  const srcExt      = src || ext;

  const handleApplyTrim = (start, end) => {
    const trim = { start, end };
    setSavedTrim(trim);
    setTrimOpen(false);
    onTrimApply?.(id, start, end);
  };

  const handleOpenFolder = () => {
    if (output_path) onOpenFolder?.(output_path);
    else if (path)   onOpenFolder?.(path);
  };

  return (
    <div className={rowCls}>
      <div className="row-line">
        <div className="tile" style={{ background: `linear-gradient(150deg, ${rowFmtColor(ext)}, ${rowFmtColor(ext)}cc)` }}>
          {ext.toUpperCase()}
          <span className="play-ov"><Icons.play size={11} style={{ color: rowFmtColor(ext) }} /></span>
        </div>

        <div className="row-main">
          <div className="row-top">
            <span className="row-name">{name}.{ext}</span>
            <span className="conv-chip">
              {srcExt.toUpperCase()} <span className="arrow"><Icons.convert size={13} /></span> <span className="to">{targetLabel}</span>
            </span>
            {savedTrim && (
              <span className="trim-range-badge">
                <Icons.trim size={11} />
                {hmsShort(savedTrim.start)} – {hmsShort(savedTrim.end)}
              </span>
            )}
            {status === "paused" && paused_at > 0 && (
              <span className="paused-at"><Icons.clock size={11} /> {hmsShort(paused_at)}</span>
            )}
          </div>
          {status === "error"
            ? <div className="err-note"><Icons.alert size={13} /> {error || "Conversion failed"}</div>
            : <div className="row-path">{path}</div>}
        </div>

        <div className="row-right">
          {status === "converting" ? (
            <div className="row-prog-wrap">
              <div className="row-prog"><i style={{ width: progress + "%" }} /></div>
              <div className="row-prog-pct">{Math.round(progress)}%</div>
            </div>
          ) : (
            <span className="row-size">{size}</span>
          )}

          <StatusPill status={status} />

          <div className="row-actions">
            <button
              className={"trim-btn" + (trimOpen || savedTrim ? " open" : "")}
              onClick={() => setTrimOpen((o) => !o)}
            >
              <Icons.trim size={15} /> Trim
              <Icons.chevron size={13} style={{ transform: trimOpen ? "rotate(180deg)" : "none", transition: ".15s" }} />
            </button>
            {status === "converting" && (
              <button className="ico-btn pause-btn" title="Pause this file" onClick={() => onPause?.(id)}>
                <Icons.pause size={16} />
              </button>
            )}
            {status === "paused" && (
              <button className="ico-btn resume-btn" title="Resume this file" onClick={() => onResume?.(id)}>
                <Icons.play size={16} />
              </button>
            )}
            {status === "done" && (
              <button className="ico-btn" title="Open output folder" onClick={handleOpenFolder}>
                <Icons.folderOpen size={17} />
              </button>
            )}
            <button className="ico-btn danger" title="Remove" onClick={() => onRemove(id)}>
              <Icons.x size={16} />
            </button>
          </div>
        </div>
      </div>

      {trimOpen && (
        <TrimPanel file={file} savedTrim={savedTrim} onApplyTrim={handleApplyTrim} />
      )}
    </div>
  );
}

function EmptyState({ onAdd }) {
  return (
    <div className="empty">
      <div className="empty-card">
        <div className="empty-ill">
          <Icons.upload size={42} sw={1.6} />
          <Icons.sparkle size={18} className="sparkle" style={{ top: 14, right: 18, color: "#ff9b59" }} />
          <Icons.sparkle size={12} className="sparkle" style={{ bottom: 16, left: 20, color: "#ffc59e" }} />
        </div>
        <h2>Your queue is empty</h2>
        <p>Add video files from your computer to start converting. Every common format is supported.</p>
        <button className="btn btn-primary" style={{ margin: "0 auto", padding: "12px 22px" }} onClick={onAdd}>
          <Icons.filePlus size={17} /> Add Files
        </button>
      </div>
    </div>
  );
}

function BottomBar({ files, running, elapsed, overall, label, buttonLabel, onToggleRun }) {
  const total = files.length;
  const done  = files.filter((f) => f.status === "done").length;
  const fmtTime = (s) => {
    const m = Math.floor(s / 60), sec = s % 60;
    return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };
  return (
    <div className="bottombar">
      <div className="bb-stat">
        <span className="k">Files</span>
        <span className="v">{done} / {total}</span>
      </div>
      <div className="bb-sep" />
      <div className="bb-stat">
        <span className="k">Elapsed</span>
        <span className={"v" + (running ? " run" : "")}>{fmtTime(elapsed)}</span>
      </div>
      <div className="bb-sep" />
      <div className="bb-prog-block">
        <div className="bb-prog-top">
          <span className="lbl">{label}</span>
          <span className="pct">{Math.round(overall)}%</span>
        </div>
        <div className="bb-prog"><i style={{ width: overall + "%" }} /></div>
      </div>
      <button
        className={"btn btn-primary btn-start" + (running ? " running" : "")}
        onClick={onToggleRun}
        disabled={total === 0}
        style={total === 0 ? { opacity: .45, cursor: "not-allowed" } : null}
      >
        {running
          ? <><Icons.pause size={17} /> Pause</>
          : buttonLabel === "Resume"
            ? <><Icons.play size={16} /> Resume</>
            : <><Icons.play size={16} /> Start Conversion</>}
      </button>
    </div>
  );
}

window.Object.assign(window, { FileRow, EmptyState, BottomBar, StatusPill });
