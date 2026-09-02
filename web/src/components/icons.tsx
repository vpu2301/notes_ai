// Tiny inline icon set — 1.5px stroke, 20px grid, currentColor.

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
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export function NotesIcon({ size = 18 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M5 2.75h7.5L16 6.25v11H5z" />
      <path d="M12 3v3.5h3.5M7.5 10h5M7.5 13h5" />
    </svg>
  );
}

export function MicIcon({ size = 18 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="7.25" y="2.25" width="5.5" height="9.5" rx="2.75" />
      <path d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.75" />
    </svg>
  );
}

export function PlusIcon({ size = 18 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M10 4.5v11M4.5 10h11" />
    </svg>
  );
}

export function BellIcon({ size = 18 }: IconProps) {
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
