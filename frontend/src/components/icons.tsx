import type { SVGProps } from 'react'

// Small stroke icon set (24px grid, currentColor) so the app ships no icon font.
type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Icon({ size = 18, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const IconDashboard = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 13h6V4H4zM14 20h6v-9h-6zM14 4v4h6V4zM4 20h6v-4H4z" />
  </Icon>
)
export const IconSources = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8" />
    <circle cx="6" cy="18" r="1.5" />
  </Icon>
)
export const IconCrawls = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 12h3l3-7 4 14 3-7h3" />
  </Icon>
)
export const IconArticles = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 4h11l3 3v13H5zM9 9h6M9 13h6M9 17h4" />
  </Icon>
)
export const IconDebug = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-4.5-4.5M9 11h4M11 9v4" />
  </Icon>
)
export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Icon>
)
export const IconX = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
)
export const IconClock = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 8v4l3 2" />
  </Icon>
)
export const IconSpinner = (p: IconProps) => (
  <Icon {...p} className={`spin ${p.className ?? ''}`}>
    <path d="M12 4a8 8 0 1 1-8 8" />
  </Icon>
)
export const IconMinus = (p: IconProps) => (
  <Icon {...p}>
    <path d="M7 12h10" />
  </Icon>
)
export const IconPlay = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 5.5v13l10-6.5z" />
  </Icon>
)
export const IconPlus = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)
export const IconExternal = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 5h5v5M19 5l-8 8M17 14v5H5V7h5" />
  </Icon>
)
export const IconSun = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
)
export const IconMoon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  </Icon>
)
export const IconMenu = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)
export const IconSignOut = (p: IconProps) => (
  <Icon {...p}>
    <path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10" />
  </Icon>
)
export const IconWarning = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 4 2.5 20h19zM12 10v4M12 17v.5" />
  </Icon>
)
export const IconTeam = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="9" cy="8" r="3.5" />
    <path d="M2.5 19.5c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5M16 4.8a3.5 3.5 0 0 1 0 6.4M18.5 14.4c1.5.9 2.6 2.7 3 5.1" />
  </Icon>
)
