/* Rounded line icons — strokeWidth 1.8, round caps. */
const I = ({ d, size = 18, fill, sw = 1.8, children, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill || "none"}
    stroke={fill ? "none" : "currentColor"} strokeWidth={sw}
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    {d ? <path d={d} /> : children}
  </svg>
);

const Icons = {
  filePlus: (p) => <I {...p}><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z"/><path d="M12 11v6M9 14h6"/></I>,
  folderPlus: (p) => <I {...p}><path d="M3 8a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.4.6L11.8 8H19a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z"/><path d="M12 12v4M10 14h4"/></I>,
  folder: (p) => <I {...p}><path d="M3 8a2 2 0 0 1 2-2h3.6a2 2 0 0 1 1.4.6L11.8 8H19a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z"/></I>,
  folderOpen: (p) => <I {...p}><path d="M4 19l2.5-7a2 2 0 0 1 1.9-1.4H21l-2.4 7A2 2 0 0 1 16.7 19H4Z"/><path d="M4 19V7a2 2 0 0 1 2-2h3.5a2 2 0 0 1 1.4.6L12.5 7H18a2 2 0 0 1 2 2v1.6"/></I>,
  queue: (p) => <I {...p}><path d="M4 7h16M4 12h16M4 17h9"/><circle cx="18.5" cy="17" r="2.2"/></I>,
  history: (p) => <I {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 4v4h4"/><path d="M12 8v4l3 2"/></I>,
  settings: (p) => <I {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a7.9 7.9 0 0 0 0-3l1.7-1.3-1.8-3.2-2 .8a7.7 7.7 0 0 0-2.6-1.5L14.3 3H9.7l-.4 2.3a7.7 7.7 0 0 0-2.6 1.5l-2-.8L2.9 9.2l1.7 1.3a7.9 7.9 0 0 0 0 3l-1.7 1.3 1.8 3.2 2-.8a7.7 7.7 0 0 0 2.6 1.5l.4 2.3h4.6l.4-2.3a7.7 7.7 0 0 0 2.6-1.5l2 .8 1.8-3.2-1.7-1.3Z"/></I>,
  info: (p) => <I {...p}><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></I>,
  logs: (p) => <I {...p}><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z"/><path d="M9 13h6M9 17h4"/></I>,
  trim: (p) => <I {...p}><circle cx="6" cy="7" r="2.4"/><circle cx="6" cy="17" r="2.4"/><path d="M8 8.3 20 16M8 15.7 20 8M8.5 12H13"/></I>,
  x: (p) => <I {...p}><path d="M18 6 6 18M6 6l12 12"/></I>,
  chevron: (p) => <I {...p} sw={2}><path d="m6 9 6 6 6-6"/></I>,
  play: (p) => <I {...p}><path d="M7 5.5v13l11-6.5-11-6.5Z" fill="currentColor" stroke="none"/></I>,
  pause: (p) => <I {...p}><rect x="7" y="6" width="3.5" height="12" rx="1.2" fill="currentColor" stroke="none"/><rect x="13.5" y="6" width="3.5" height="12" rx="1.2" fill="currentColor" stroke="none"/></I>,
  check: (p) => <I {...p} sw={2.4}><path d="m5 12.5 4.5 4.5L19 7"/></I>,
  loader: (p) => <I {...p} sw={2.2}><path d="M12 3a9 9 0 1 0 9 9" /></I>,
  alert: (p) => <I {...p}><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></I>,
  clock: (p) => <I {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></I>,
  search: (p) => <I {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/></I>,
  film: (p) => <I {...p}><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4"/></I>,
  min: (p) => <I {...p} sw={1.6}><path d="M6 12h12"/></I>,
  max: (p) => <I {...p} sw={1.6}><rect x="6" y="6" width="12" height="12" rx="2"/></I>,
  convert: (p) => <I {...p}><path d="M4 8h12l-3-3M20 16H8l3 3"/></I>,
  sparkle: (p) => <I {...p}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/></I>,
  upload: (p) => <I {...p}><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></I>,
};

window.Icons = Icons;
