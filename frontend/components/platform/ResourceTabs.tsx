import Link from "next/link";

export function ResourceTabs({ tabs }: { tabs: { href: string; label: string }[] }) {
  return (
    <nav className="topbar-breadcrumbs" aria-label="Resource tabs" style={{ marginBottom: 12 }}>
      {tabs.map((tab) => (
        <Link key={tab.href} href={tab.href} className="topbar-pill">
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
