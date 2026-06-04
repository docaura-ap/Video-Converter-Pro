const { useState, useRef, useEffect } = React;
const { fmtColor } = window.VCData;

/* ── Generic dropdown ── */
function Dropdown({ value, options, onChange, align = "left", renderDot }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const cur = options.find((o) => o.id === value) || options[0];
  return (
    <div className="dd" ref={ref}>
      <button className="dd-btn" onClick={() => setOpen((o) => !o)}>
        {renderDot && <span className="fmt-dot" style={{ background: renderDot(cur.id) }} />}
        <span>{cur.label}</span>
        <Icons.chevron size={14} style={{ color: "var(--ink-3)", transform: open ? "rotate(180deg)" : "none", transition: ".15s" }} />
      </button>
      {open && (
        <div className={"dd-menu" + (align === "right" ? " right" : "")}>
          {options.map((o) => (
            <div key={o.id} className={"dd-opt" + (o.id === value ? " sel" : "")}
              onClick={() => { onChange(o.id); setOpen(false); }}>
              {renderDot && <span className="fmt-dot" style={{ background: renderDot(o.id) }} />}
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <span>{o.label}</span>
                {o.note && <span style={{ fontSize: 10.5, color: "var(--ink-3)", fontWeight: 500 }}>{o.note}</span>}
              </div>
              {o.id === value && <Icons.check size={15} className="check" />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Title bar — wired to pywebview window controls ── */
function TitleBar() {
  const call = (fn) => window.pywebview?.api[fn]?.();
  return (
    <div className="titlebar" onDoubleClick={() => call("toggle_maximize")}>
      <span className="tb-dot"><Icons.film size={11} /></span>
      <span className="tb-title">Video Converter Pro</span>
      <span className="tb-spacer" />
      <div className="tb-btns">
        <button className="tb-btn" title="Minimize" onClick={() => call("minimize_window")}><Icons.min size={16} /></button>
        <button className="tb-btn" title="Maximize" onClick={() => call("toggle_maximize")}><Icons.max size={13} /></button>
        <button className="tb-btn close" title="Close" onClick={() => call("close_window")}><Icons.x size={15} /></button>
      </div>
    </div>
  );
}

/* ── Sidebar ── */
function NavItem({ icon, label, active, onClick }) {
  const Ico = Icons[icon];
  return (
    <div className={"nav-item" + (active ? " active" : "")} onClick={onClick}>
      <span className="ni-ico"><Ico size={18} /></span>
      <span>{label}</span>
    </div>
  );
}

function Rule({ label, danger, on, onToggle }) {
  return (
    <div className={"rule" + (danger ? " danger" : "")} onClick={onToggle}>
      <span className="rule-txt">{label}</span>
      <span className={"switch" + (on ? " on" : "")} />
    </div>
  );
}

function Sidebar({ onAddFiles, onAddFolder, onOpenHistory, onOpenAbout, onOpenLogs, rules, setRules }) {
  return (
    <aside className="side">
      <div className="brand">
        <span className="brand-mark"><Icons.convert size={22} sw={2} /></span>
        <div>
          <div className="brand-name">Video Converter<br />Pro</div>
          <div className="brand-ver">v1</div>
        </div>
      </div>

      <div className="cta-col">
        <button className="btn btn-primary" onClick={onAddFiles}><Icons.filePlus size={17} /> Add Files</button>
        <button className="btn btn-ghost" onClick={onAddFolder}><Icons.folderPlus size={17} /> Add Folder</button>
      </div>

      <div className="nav-group">
        <div className="nav-label">Converter</div>
        <NavItem icon="queue"   label="Conversion Queue"    active />
        <NavItem icon="history" label="Session History"     onClick={onOpenHistory} />
        <NavItem icon="info"    label="About & Engine Info" onClick={onOpenAbout} />
      </div>

      <div className="nav-group">
        <div className="nav-label">Local File Rules</div>
        <div className="rules">
          <Rule label="Keep source directory" on={rules.keep}
            onToggle={() => setRules((r) => ({ ...r, keep: !r.keep }))} />
          <Rule label="Delete original file" danger on={rules.del}
            onToggle={() => setRules((r) => ({ ...r, del: !r.del }))} />
        </div>
      </div>

      <div className="side-spacer" />
      <button className="btn btn-ghost logs-btn" onClick={onOpenLogs}>
        <Icons.folderOpen size={17} /> Open Logs Folder
      </button>
    </aside>
  );
}

window.Object.assign(window, { Dropdown, TitleBar, Sidebar, NavItem, Rule });
