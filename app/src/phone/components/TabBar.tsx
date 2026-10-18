import { NavLink } from 'react-router-dom';

const TABS = [
  { to: '/', label: 'Answer', icon: <ListIcon /> },
  { to: '/lens', label: 'Lens', icon: <LensIcon /> },
  { to: '/sops', label: 'SOPs', icon: <DocIcon /> },
];

export function TabBar() {
  return (
    <nav className="tabbar" aria-label="Displays">
      {TABS.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end className={({ isActive }) => `tab${isActive ? ' on' : ''}`}>
          {tab.icon}
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

const box = {
  width: 22,
  height: 22,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'square' as const,
  strokeLinejoin: 'miter' as const,
};

function ListIcon() {
  return (
    <svg {...box} aria-hidden="true">
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

function LensIcon() {
  return (
    <svg {...box} aria-hidden="true">
      <circle cx="6.5" cy="13" r="3.5" />
      <circle cx="17.5" cy="13" r="3.5" />
      <path d="M10 13h4M3 9l1-3M21 9l-1-3" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg {...box} aria-hidden="true">
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v4h4M10 12h6M10 16h6" />
    </svg>
  );
}
