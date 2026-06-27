const sections = [
  {
    title: "Start A Workspace",
    items: [
      "Use Workspace as the home for folders, SQL files, notebooks, dashboards, pipelines, models, and dataset links.",
      "Create folders for teams or projects, then add assets from the action buttons in the workspace table.",
      "Use the inspector to rename items, review permissions, and remove workspace links.",
    ],
  },
  {
    title: "Bring Data In",
    items: [
      "Open Connectors to add CSV, Parquet, Postgres, or REST sources.",
      "After a connector loads, check Catalog for schema, columns, row counts, branches, lineage, and exploration links.",
      "Use Explore or the command palette to find datasets, pipelines, objects, and saved queries quickly.",
    ],
  },
  {
    title: "Build Pipelines",
    items: [
      "Open Pipelines to create visual flows from source datasets, joins, filters, selects, and outputs.",
      "Use the node inspector to configure each operation and Preview to validate the result before saving.",
      "Run pipelines from the editor, then monitor background execution in Jobs.",
    ],
  },
  {
    title: "Use Code Repositories",
    items: [
      "Write transforms in transforms.py with @transform, Input, and Output. The runner supplies those symbols automatically.",
      "Run Tests executes pytest files such as test_transforms.py. The default fixture transformed_df runs the first transform against sample customer data.",
      "Commit stores the current files in the demo Git repository. If Git errors appear after dependency changes, rebuild the backend image.",
    ],
  },
  {
    title: "Analyze And Publish",
    items: [
      "Use SQL for ad-hoc queries and AI-assisted SQL generation against catalog datasets.",
      "Use Notebooks for Python analysis with governed dataset access.",
      "Use Dashboards to bind charts and tables to saved SQL or dataset outputs.",
    ],
  },
  {
    title: "Operate And Govern",
    items: [
      "Jobs shows execution state for pipelines, notebooks, model training, connector syncs, and scheduled reports.",
      "Schedules manages recurring work, while Audit records operational events.",
      "Users, Ontology, and Resource Governance manage access, object modeling, data markings, and policy controls.",
    ],
  },
];

const quickFixes = [
  {
    symptom: "gitpython is not installed",
    fix: "Rebuild backend containers so GitPython and the git executable are installed: docker compose build backend worker beat migrate && docker compose up -d.",
  },
  {
    symptom: "Frontend port 3000 is already in use",
    fix: "Stop the local process on port 3000 or run Compose with another host port, for example FRONTEND_PORT=3001 docker compose up -d.",
  },
  {
    symptom: "Code tests fail for transformed_df",
    fix: "Keep tests named test_*.py and use the transformed_df fixture, or add your own conftest.py when you need custom fixtures.",
  },
];

export default function HelpPage() {
  return (
    <div className="space-y-6">
      <header className="page-header">
        <div>
          <div className="page-header-eyebrow">System Guide</div>
          <h1 className="page-header-title">Help Guide</h1>
          <p className="page-header-subtitle">
            Practical steps for loading data, building workflows, testing transforms, and operating Mini Foundry.
          </p>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sections.map((section) => (
          <article key={section.title} className="app-card p-4">
            <h2 className="text-sm font-semibold">{section.title}</h2>
            <ul className="mt-3 space-y-2">
              {section.items.map((item) => (
                <li key={item} className="flex gap-2 text-[12.5px]" style={{ color: "var(--text-2)" }}>
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "var(--accent)" }} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="app-card">
        <div className="section-header">
          <span className="section-header-title">Common Fixes</span>
        </div>
        <div className="divide-y" style={{ borderColor: "var(--line)" }}>
          {quickFixes.map((item) => (
            <div key={item.symptom} className="grid gap-2 p-4 md:grid-cols-[220px_1fr]">
              <div className="badge badge-warning">{item.symptom}</div>
              <div className="font-mono text-xs" style={{ color: "var(--text-2)" }}>{item.fix}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
