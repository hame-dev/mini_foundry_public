"use client";

import { PlatformAreaPage } from "@/components/platform/PlatformAreaPage";

const LINKS = [
  { href: "/settings/profile", label: "Profile" },
  { href: "/settings/organization", label: "Organization" },
  { href: "/settings/project-templates", label: "Project templates" },
  { href: "/settings/ai", label: "AI providers" },
  { href: "/settings/feature-flags", label: "Feature flags" },
  { href: "/settings/theme", label: "Theme" },
  { href: "/settings/keyboard-shortcuts", label: "Keyboard shortcuts" },
];

export default function SettingsPage() {
  return <PlatformAreaPage title="Settings" type="Settings" links={LINKS} />;
}
