import type { NextConfig } from "next";

const config: NextConfig = {
  outputFileTracingRoot: process.cwd(),
  reactStrictMode: true,
  async redirects() {
    return [
      { source: "/connectors", destination: "/data/sources", permanent: false },
      { source: "/connectors/:path*", destination: "/data/sources/:path*", permanent: false },
      { source: "/catalog", destination: "/data/catalog", permanent: false },
      { source: "/catalog/lineage", destination: "/data/lineage", permanent: false },
      { source: "/catalog/:id/explore", destination: "/data/datasets/:id/explore", permanent: false },
      { source: "/catalog/:id/branches", destination: "/data/datasets/:id/branches", permanent: false },
      { source: "/catalog/:id", destination: "/data/datasets/:id", permanent: false },
      { source: "/explore", destination: "/analytics/explore", permanent: false },
      { source: "/sql", destination: "/analytics/sql", permanent: false },
      { source: "/pipelines", destination: "/build/pipelines", permanent: false },
      { source: "/pipelines/:path*", destination: "/build/pipelines/:path*", permanent: false },
      { source: "/builds", destination: "/build/runs", permanent: false },
      { source: "/dashboards", destination: "/apps/dashboards", permanent: false },
      { source: "/dashboards/:path*", destination: "/apps/dashboards/:path*", permanent: false },
      { source: "/applications", destination: "/apps/builder", permanent: false },
      { source: "/notebooks", destination: "/develop/notebooks", permanent: false },
      { source: "/notebooks/:path*", destination: "/develop/notebooks/:path*", permanent: false },
      { source: "/code-repo", destination: "/develop/code", permanent: false },
      { source: "/code-repo/:path*", destination: "/develop/code/:path*", permanent: false },
      { source: "/models", destination: "/develop/models", permanent: false },
      { source: "/object-explorer", destination: "/ontology/explorer", permanent: false },
      { source: "/admin/ontology", destination: "/ontology/manager", permanent: false },
      { source: "/admin/users", destination: "/governance/users", permanent: false },
      { source: "/admin/audit", destination: "/governance/audit", permanent: false },
      { source: "/admin/jobs", destination: "/operations/jobs", permanent: false },
      { source: "/admin/schedules", destination: "/operations/schedules", permanent: false },
      { source: "/quiver", destination: "/analytics/quiver", permanent: false },
      { source: "/aip-logic", destination: "/ai/logic", permanent: false },
    ];
  },
};

export default config;
