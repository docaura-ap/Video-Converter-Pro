const { useState: useTrimState, useRef: useTrimRef } = React;

const hms = (sec) => {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
};
const parseHms = (str, max) => {
  const p = str.split(":").map((n) => parseInt(n, 10) || 0);
  while (p.length < 3) p.unshift(0);
  return Math.min(max, Math.max(0, p[0] * 3600 + p[1] * 60 + p[2]));
};

function TrimPanel({ file, savedTrim, onApplyTrim }) {
  const total = file.duration || 180;
  const [start, setStart] = useTrimState(savedTrim ? savedTrim.start : 0);
  const [end, setEnd]     = useTrimState(savedTrim ? savedTrim.end   : total);
  const trackRef = useTrimRef(null);
  const dragRef  = useTrimRef(null);

  const pct = (v) => (total ? (v / total) * 100 : 0);

  const onDown = (which) => (e) => {
    e.preventDefault();
    dragRef.current = which;
    const move = (ev) => {
      const rect = trackRef.current.getBoundingClientRect();
      const cx = ev.touches ? ev.touches[0].clientX : ev.clientX;
      const r  = Math.min(1, Math.max(0, (cx - rect.left) / rect.width));
      const sec = Math.round(r * total);
      if (dragRef.current === "start") setStart(Math.min(sec, end - 1));
      else                             setEnd(Math.max(sec, start + 1));
    };
    const up = () => {
      dragRef.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup",   up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup",   up);
  };

  return (
    <div className="trim-panel">
      {/* Track — overflow:visible so handles at 0% and 100% are never clipped */}
      <div className="trim-track-wrap">
        <div className="trim-track" ref={trackRef}>
          {/* film strips clipped by their own wrapper */}
          <div className="film-clip">
            <div className="film">{Array.from({ length: 14 }).map((_, i) => <span key={i} />)}</div>
          </div>
          {/* selection overlay */}
          <div className="trim-sel" style={{ left: pct(start) + "%", right: (100 - pct(end)) + "%" }} />
          {/* handles — inside track, track is overflow:visible */}
          <div className="trim-handle" style={{ left: pct(start) + "%" }} onPointerDown={onDown("start")} />
          <div className="trim-handle" style={{ left: pct(end)   + "%" }} onPointerDown={onDown("end")}   />
        </div>
      </div>

      <div className="trim-fields">
        <div className="trim-field">
          <label>Start time</label>
          <input className="time-input" value={hms(start)}
            onChange={(e) => setStart(parseHms(e.target.value, end - 1))} />
        </div>
        <div className="trim-field">
          <label>End time</label>
          <input className="time-input" value={hms(end)}
            onChange={(e) => setEnd(parseHms(e.target.value, total))} />
        </div>
        <span className="trim-dur"><Icons.trim size={12} /> Output {hms(end - start)}</span>
        <span className="trim-spacer" />
        <button className="btn btn-ghost btn-sm" onClick={() => { setStart(0); setEnd(total); }}>Reset</button>
        <button className="btn btn-primary btn-sm" onClick={() => onApplyTrim(start, end)}>
          <Icons.check size={15} /> Apply trim
        </button>
      </div>
    </div>
  );
}

window.Object.assign(window, { TrimPanel });
