"use client";

import { use } from "react";
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

export default function SettingsSubroutePage({ params }: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = use(params);
  const title = ["Settings", ...path]
    .map((part) => part.replace(/-/g, " "))
    .join(" / ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

  return <PlatformAreaPage title={title} type="Settings" links={LINKS} />;
}
