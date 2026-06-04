/* ── Static metadata only — no fake file data ── */

const FORMAT_COLOR = {
  mp4:  "#ff6b3d", mkv: "#3b82f6", mov: "#8b5cf6", avi: "#0ea5a3",
  mpeg: "#d9912b", mpg: "#d9912b", mts: "#e9495f", mxf: "#6366f1",
  ogv:  "#16a34a", rm: "#64748b", ts: "#0891b2", vob: "#db2777",
  webm: "#22a06b", wmv: "#2563eb", wtv: "#7c3aed", flv: "#ea580c",
  m4v:  "#f43f5e", "3gp": "#0d9488", mp3: "#e11d48",
  hevc: "#0891b2", m2v: "#6366f1", f4v: "#d97706", wav: "#059669",
  aac:  "#7c3aed", ogg: "#16a34a", flac: "#1d4ed8", wma: "#2563eb",
};
const fmtColor = (ext) => FORMAT_COLOR[(ext || "").replace(/\W/g, "")] || "#7c6f60";

const OUTPUT_FORMATS = [
  { id: "mp4",          label: "MP4",          note: "H.264 · most compatible" },
  { id: "mkv",          label: "MKV",          note: "Matroska · flexible" },
  { id: "avi",          label: "AVI",          note: "Legacy container" },
  { id: "mov",          label: "MOV",          note: "Apple QuickTime" },
  { id: "webm",         label: "WebM",         note: "VP9 · web optimized" },
  { id: "mp4 (h.265)",  label: "MP4 (H.265)",  note: "HEVC · smaller files" },
  { id: "mp3",          label: "MP3",          note: "Audio only" },
];

const QUALITY_PRESETS = [
  { id: "Ultra",    label: "Ultra",    note: "Best quality · slow" },
  { id: "High",     label: "High",     note: "Great quality" },
  { id: "Balanced", label: "Balanced", note: "Quality & speed" },
  { id: "Fast",     label: "Fast",     note: "Speed first" },
];

const GPU_OPTIONS = [
  { id: "CPU",           label: "CPU",          note: "Software encoding" },
  { id: "NVIDIA (NVENC)",label: "NVIDIA (NVENC)",note: "NVENC hardware" },
  { id: "Intel (QSV)",   label: "Intel (QSV)",  note: "Quick Sync" },
  { id: "AMD (AMF)",     label: "AMD (AMF)",    note: "AMF hardware" },
];

const PARALLEL_OPTIONS = [
  { id: "1", label: "1", note: "One at a time" },
  { id: "2", label: "2", note: "Two in parallel" },
  { id: "3", label: "3", note: "Three in parallel" },
  { id: "4", label: "4", note: "Four in parallel" },
];

const labelOf = (list, id) => (list.find((o) => o.id === id) || list[0]).label;

window.VCData = {
  FORMAT_COLOR, fmtColor,
  OUTPUT_FORMATS, QUALITY_PRESETS, GPU_OPTIONS, PARALLEL_OPTIONS,
  labelOf,
};
