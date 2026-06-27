"use client";

import Link from "next/link";
import { LineageGraph } from "@/components/catalog/LineageGraph";

export default function CatalogLineagePage() {
  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header-eyebrow">Build · Catalog</div>
          <h1 className="page-header-title">Data lineage</h1>
          <div className="page-header-subtitle">
            Visualize the end-to-end data flow, transformations, and dependency lineage.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/catalog" className="btn-secondary">
            <span>List view</span>
          </Link>
        </div>
      </div>

      <div className="app-card overflow-hidden p-2">
        <LineageGraph />
      </div>
    </div>
  );
}
