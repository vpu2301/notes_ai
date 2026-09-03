// Inline icon set — 1.6px stroke, 20px grid, currentColor.

interface IconProps {
  size?: number;
}

function base(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export function NotesIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M5 2.75h7.5L16 6.25v11H5z" />
      <path d="M12 3v3.5h3.5M7.5 10h5M7.5 13h5" />
    </svg>
  );
}

export function InboxIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3 11.5 5 4.5h10l2 7v4H3z" />
      <path d="M3 11.5h4l1.2 2h3.6l1.2-2h4" />
    </svg>
  );
}

export function MicIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="7.25" y="2.25" width="5.5" height="9.5" rx="2.75" />
      <path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.75" />
    </svg>
  );
}

export function WaveformIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3 8.5v3M6.5 5.5v9M10 3v14M13.5 6.5v7M17 8.5v3" />
    </svg>
  );
}

export function LayersIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m10 3 7 3.5-7 3.5-7-3.5z" />
      <path d="m3 10 7 3.5 7-3.5M3 13.5 10 17l7-3.5" />
    </svg>
  );
}

export function PlusIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 4.5v11M4.5 10h11" />
    </svg>
  );
}

export function BellIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 2.75a5 5 0 0 0-5 5v3l-1.5 3h13l-1.5-3v-3a5 5 0 0 0-5-5zM8 14.5a2 2 0 0 0 4 0" />
    </svg>
  );
}

export function SearchIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="9" cy="9" r="5.25" />
      <path d="m13 13 4 4" />
    </svg>
  );
}

export function DownloadIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 3v9m0 0 3.5-3.5M10 12 6.5 8.5M3.5 15.5h13" />
    </svg>
  );
}

export function HistoryIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3.5 10a6.5 6.5 0 1 1 1.9 4.6M3.5 10V6.5M3.5 10H7" />
      <path d="M10 6.5V10l2.5 1.5" />
    </svg>
  );
}

export function LogoutIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M8 3.5H4.5v13H8M12.5 6.5 16 10l-3.5 3.5M16 10H7.5" />
    </svg>
  );
}

export function UploadIcon({ size = 24 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 13V4m0 0L6.5 7.5M10 4l3.5 3.5M3.5 15.5h13" />
    </svg>
  );
}

export function StopIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="5" y="5" width="10" height="10" rx="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function CloseIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m5 5 10 10M15 5 5 15" />
    </svg>
  );
}

export function CheckIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m4 10.5 4 4 8-9" />
    </svg>
  );
}

export function ChevronLeftIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m12.5 4.5-5 5.5 5 5.5" />
    </svg>
  );
}

export function ChevronRightIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m7.5 4.5 5 5.5-5 5.5" />
    </svg>
  );
}

export function ChevronDownIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m4.5 7.5 5.5 5 5.5-5" />
    </svg>
  );
}

export function ArrowLeftIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M16 10H4m0 0 5-5m-5 5 5 5" />
    </svg>
  );
}

export function SunIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="10" cy="10" r="3.25" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </svg>
  );
}

export function MoonIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M16.5 12.2A7 7 0 0 1 7.8 3.5a7 7 0 1 0 8.7 8.7z" />
    </svg>
  );
}

export function MonitorIcon({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="2.75" y="3.75" width="14.5" height="9.5" rx="1.75" />
      <path d="M7 16.5h6M10 13.5v3" />
    </svg>
  );
}

export function UserIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="10" cy="7" r="3.25" />
      <path d="M3.75 17a6.25 6.25 0 0 1 12.5 0" />
    </svg>
  );
}

export function FileTextIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M5.5 2.75h6l3 3v11.5h-9z" />
      <path d="M11.5 3v3h3M8 10h4M8 13h4" />
    </svg>
  );
}

export function PenIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="m3.5 16.5 1-4L13.5 3.5l3 3-9 9z" />
      <path d="m11.5 5.5 3 3" />
    </svg>
  );
}

export function AlertIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 3.25 17.25 16H2.75z" />
      <path d="M10 8v3.5M10 13.75v.25" />
    </svg>
  );
}

export function ClockIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="10" cy="10" r="6.75" />
      <path d="M10 6.5V10l2.5 1.5" />
    </svg>
  );
}

export function MoreIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="4.5" cy="10" r="1" fill="currentColor" />
      <circle cx="10" cy="10" r="1" fill="currentColor" />
      <circle cx="15.5" cy="10" r="1" fill="currentColor" />
    </svg>
  );
}

export function CopyIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M13 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" />
    </svg>
  );
}

export function SettingsIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3 6h9M15 6h2M3 14h2M8 14h9" />
      <circle cx="13" cy="6" r="2" />
      <circle cx="6" cy="14" r="2" />
    </svg>
  );
}

export function ShareIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="15" cy="5" r="2.2" />
      <circle cx="5" cy="10" r="2.2" />
      <circle cx="15" cy="15" r="2.2" />
      <path d="M7 9l6-3M7 11l6 3" />
    </svg>
  );
}

export function TrashIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M4 6h12M8 6V4h4v2M6 6l.8 10h6.4L14 6" />
      <path d="M8.5 9v4M11.5 9v4" />
    </svg>
  );
}

export function FileDownIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M6 3h5l4 4v10H6z" />
      <path d="M11 3v4h4" />
      <path d="M10 9v5M8 12l2 2 2-2" />
    </svg>
  );
}

export function CalendarIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="3" y="4.5" width="14" height="12.5" rx="2.5" />
      <path d="M3 8.5h14M7 2.5v3.5M13 2.5v3.5" />
    </svg>
  );
}

export function CalendarClockIcon({ size = 24 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3 8.5h9M6.5 2.5v3.5M11.5 2.5v3.5" />
      <path d="M9.5 16.5H5.5A2.5 2.5 0 0 1 3 14V6.5A2.5 2.5 0 0 1 5.5 4h7A2.5 2.5 0 0 1 15 6.5V9" />
      <circle cx="14.5" cy="14.5" r="3.6" />
      <path d="M14.5 12.7v1.9l1.3 1" />
    </svg>
  );
}

export function VideoIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="2.5" y="5.5" width="11" height="9" rx="2" />
      <path d="M13.5 9l4-2.5v7l-4-2.5" />
    </svg>
  );
}

export function RefreshIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M16.5 10a6.5 6.5 0 1 1-1.9-4.6" />
      <path d="M16.5 3.5v4h-4" />
    </svg>
  );
}

export function LinkOffIcon({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M8 12l4-4M7.5 5.5l1-1a3 3 0 0 1 4.3 4.3l-1 1M12.5 14.5l-1 1a3 3 0 0 1-4.3-4.3l1-1" />
      <path d="M3.5 3.5l13 13" />
    </svg>
  );
}
