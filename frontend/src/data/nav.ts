// ============================================================
// NAV MODEL — single source of truth for sidebar + router + header
// ============================================================

export interface NavItem {
  idx: string
  label: string
  name: string
  icon: string
  status: string
  badge?: string
}

export const NAV: NavItem[] = [
  { idx: '01', label: 'Overview',           name: 'overview',   icon: 'overview',   status: 'active' },
  { idx: '02', label: 'Memory',             name: 'memory',     icon: 'memory',     status: 'active' },
  { idx: '03', label: 'Email Intelligence', name: 'email',      icon: 'email',      status: 'standby' },
  { idx: '04', label: 'Bank Adviser',       name: 'bank',       icon: 'bank',       status: 'error' },
  { idx: '05', label: 'Health Intel',       name: 'health',     icon: 'health',     status: 'active' },
  { idx: '06', label: 'Job Agent',          name: 'job',        icon: 'job',        status: 'classified', badge: 'CLASSIFIED' },
  { idx: '07', label: 'Hermes',             name: 'hermes',     icon: 'hermes',     status: 'standby' },
  { idx: '08', label: 'Pulse',              name: 'pulse',      icon: 'pulse',      status: 'active' },
  { idx: '09', label: 'Signal',             name: 'signal',     icon: 'signal',     status: 'active' },
]

export const SETTINGS: NavItem = {
  idx: '10', label: 'Settings', name: 'settings', icon: 'settings', status: 'active'
}

export const STATUS_TEXT: Record<string, string> = {
  active:     'ACTIVE',
  standby:    'STANDBY',
  processing: 'PROCESSING',
  error:      'ERROR',
  classified: 'CLASSIFIED',
}

// Geometric stroke icons — viewBox 0 0 16 16, stroke only, no fill
export const ICONS: Record<string, string> = {
  overview:   '<rect x="1.5" y="1.5" width="5" height="5"/><rect x="9.5" y="1.5" width="5" height="5"/><rect x="1.5" y="9.5" width="5" height="5"/><rect x="9.5" y="9.5" width="5" height="5"/>',
  memory:     '<rect x="4" y="4" width="8" height="8"/><rect x="6.5" y="6.5" width="3" height="3"/><path d="M6 1.5v2.5M10 1.5v2.5M6 12v2.5M10 12v2.5M1.5 6h2.5M1.5 10h2.5M12 6h2.5M12 10h2.5"/>',
  email:      '<rect x="1.5" y="3.5" width="13" height="9"/><path d="M1.5 4l6.5 5 6.5-5"/>',
  bank:       '<path d="M1.5 6L8 2l6.5 4"/><path d="M3 6.5v6M6 6.5v6M9.5 6.5v6M12.5 6.5v6"/><path d="M1.5 13.5h13"/>',
  job:        '<rect x="1.5" y="5" width="13" height="8.5"/><path d="M5.5 5V3.5h5V5"/><path d="M1.5 8.5h13"/>',
  hermes:     '<path d="M14.5 1.5L1.5 7l5 2 2 5z"/><path d="M14.5 1.5L6.5 9"/>',
  settings:   '<circle cx="8" cy="8" r="2.3"/><path d="M8 1.5v2.2M8 12.3v2.2M1.5 8h2.2M12.3 8h2.2M3.4 3.4l1.6 1.6M11 11l1.6 1.6M12.6 3.4L11 5M5 11l-1.6 1.6"/>',
  logout:     '<path d="M6 2.5H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/><path d="M9.5 11l3-3-3-3"/><path d="M12.5 8H6"/>',
  health:     '<circle cx="8" cy="8" r="5.5"/><path d="M2 8h2.5l2-4 2.5 8 2-4H14"/>',
  signal:     '<rect x="1.5" y="3.5" width="13" height="9"/><path d="M6.5 6l3.5 2-3.5 2z"/>',
  pulse:      '<circle cx="8" cy="6" r="1.3"/><path d="M8 7.3V14"/><path d="M5.5 3.5a3.5 3.5 0 0 0 0 5M10.5 3.5a3.5 3.5 0 0 1 0 5"/><path d="M3.5 1.5a6 6 0 0 0 0 9M12.5 1.5a6 6 0 0 1 0 9"/>',
}
