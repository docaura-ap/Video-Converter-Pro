const { useEffect: useModalEffect, useState: useModalState } = React;
const { fmtColor: hFmtColor } = window.VCData;

function Backdrop({ onClose, children }) {
  useModalEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      {children}
    </div>
  );
}

/* ── About & Engine Info ── */
function AboutModal({ onClose }) {
  const [info, setInfo] = useModalState([]);
  useModalEffect(() => {
    window.pywebview?.api?.get_engine_info?.().then?.((data) => {
      if (data) setInfo(data);
    });
  }, []);

  const engIcon = { "Engine": "film", "NVIDIA NVENC": "sparkle", "Intel QSV": "sparkle", "AMD AMF": "sparkle" };
  return (
    <Backdrop onClose={onClose}>
      <div className="modal about">
        <div className="modal-head">
          <span className="mh-ico"><Icons.info size={19} /></span>
          <div><h3>About &amp; Engine Info</h3></div>
          <span className="mh-spacer" />
          <button className="modal-x" onClick={onClose}><Icons.x size={17} /></button>
        </div>
        <div className="about-body">
          <div className="about-mark"><Icons.convert size={38} sw={2} /></div>
          <div className="about-name">Video Converter Pro</div>
          <div className="about-ver"><Icons.check size={13} /> Version 1</div>
          <div className="eng-list">
            {info.map((e) => {
              const Ico = Icons[engIcon[e.k] || "info"];
              return (
                <div className="eng-row" key={e.k}>
                  <span className="ico"><Ico size={16} /></span>
                  <span className="eng-k">{e.k}</span>
                  {e.status === "ok"
                    ? <span className="badge-ok"><Icons.check size={12} /> {e.v}</span>
                    : <span className="eng-v">{e.v}</span>}
                </div>
              );
            })}
            {info.length === 0 && (
              <div style={{ color: "var(--ink-3)", fontSize: 13, padding: "12px 0" }}>
                Loading engine info…
              </div>
            )}
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-primary" style={{ padding: "10px 22px" }} onClick={onClose}>Close</button>
        </div>
      </div>
    </Backdrop>
  );
}

/* ── Session History ── */
function HistoryModal({ onClose }) {
  const [rows, setRows] = useModalState(null);  // null = loading

  useModalEffect(() => {
    window.pywebview?.api?.get_history?.().then?.((data) => {
      setRows(data || []);
    });
  }, []);

  const handleClear = () => {
    window.pywebview?.api?.clear_history?.().then?.(() => setRows([]));
  };

  const fmtRow = (r) => {
    // Support both old (input_name/output_format) and new field names
    const name   = r.input_name  || r.name || "—";
    const fmt    = r.output_format || r.ext || "—";
    const size   = r.file_size   || r.size || "—";
    const dur    = r.duration    || "—";
    const status = r.status      || "—";
    const date   = r.timestamp   || r.date || "—";
    return { name, fmt, size, dur, status, date };
  };

  return (
    <Backdrop onClose={onClose}>
      <div className="modal history">
        <div className="modal-head">
          <span className="mh-ico"><Icons.history size={18} /></span>
          <div>
            <h3>Conversion History</h3>
            <div className="mh-sub">{rows === null ? "Loading…" : `${rows.length} record${rows.length !== 1 ? "s" : ""}`}</div>
          </div>
          <span className="mh-spacer" />
          <button className="link-danger" onClick={handleClear}><Icons.x size={15} /> Clear History</button>
          <button className="modal-x" onClick={onClose}><Icons.x size={17} /></button>
        </div>
        <div className="history-body">
          <div className="htable-head">
            <span>File Name</span><span>Format</span><span>Size</span>
            <span>Duration</span><span>Status</span><span>Date</span>
          </div>
          {rows === null ? (
            <div style={{ padding: "50px 0", textAlign: "center", color: "var(--ink-3)", fontSize: 13.5 }}>
              Loading history…
            </div>
          ) : rows.length === 0 ? (
            <div style={{ padding: "50px 0", textAlign: "center", color: "var(--ink-3)", fontSize: 13.5 }}>
              No conversion history yet.
            </div>
          ) : (
            <div className="htable-scroll">
              {rows.map((r, i) => {
                const { name, fmt, size, dur, status, date } = fmtRow(r);
                const ok = status === "Success" || status === "success";
                return (
                  <div className="htable-row" key={i}>
                    <span className="ht-name">{name}</span>
                    <span className="ht-fmt">
                      <span className="fmt-dot" style={{ width: 8, height: 8, borderRadius: 3, background: hFmtColor(fmt) }} />
                      {fmt}
                    </span>
                    <span className="ht-mono">{size}</span>
                    <span className="ht-mono">{dur}</span>
                    <span className={"ht-status " + (ok ? "ok" : "bad")}>
                      <span className="dot" /> {ok ? "Success" : "Failed"}
                    </span>
                    <span className="ht-date">{date}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Backdrop>
  );
}

window.Object.assign(window, { Backdrop, AboutModal, HistoryModal });
