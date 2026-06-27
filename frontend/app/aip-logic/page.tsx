"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

type LogicStep = {
  type: "llm" | "sql" | "template";
  prompt?: string;
  query?: string;
  template?: string;
  output_var: string;
};

export default function AIPLogicPage() {
  const [inputs, setInputs] = useState<Record<string, string>>({
    customer_name: "Alice",
    issue_description: "My item X was damaged during shipping.",
  });
  
  const [steps, setSteps] = useState<LogicStep[]>([
    {
      type: "llm",
      prompt: "Analyze the sentiment of this issue: {{inputs.issue_description}}. Return exactly one word: positive, negative, or neutral.",
      output_var: "sentiment",
    },
    {
      type: "template",
      template: "Customer {{inputs.customer_name}} reports a {{steps.sentiment}} issue: {{inputs.issue_description}}",
      output_var: "formatted_issue",
    },
  ]);

  const [newInputKey, setNewInputKey] = useState("");
  const [newInputValue, setNewInputValue] = useState("");

  const [showAddStep, setShowAddStep] = useState(false);
  const [newStepType, setNewStepType] = useState<"llm" | "sql" | "template">("llm");
  const [newStepVar, setNewStepVar] = useState("");
  const [newStepContent, setNewStepContent] = useState("");

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleAddInput() {
    if (!newInputKey) return;
    setInputs({ ...inputs, [newInputKey]: newInputValue });
    setNewInputKey("");
    setNewInputValue("");
  }

  function handleRemoveInput(key: string) {
    const next = { ...inputs };
    delete next[key];
    setInputs(next);
  }

  function handleAddStep(e: React.FormEvent) {
    e.preventDefault();
    if (!newStepVar) return;

    const step: LogicStep = {
      type: newStepType,
      output_var: newStepVar,
    };

    if (newStepType === "llm") step.prompt = newStepContent;
    else if (newStepType === "sql") step.query = newStepContent;
    else step.template = newStepContent;

    setSteps([...steps, step]);
    setShowAddStep(false);
    setNewStepVar("");
    setNewStepContent("");
  }

  function handleRemoveStep(idx: number) {
    const next = [...steps];
    next.splice(idx, 1);
    setSteps(next);
  }

  async function handleRunChain() {
    setRunning(true);
    setError(null);
    setResult(null);

    try {
      const out = await apiFetch<any>("/ai/logic/run", {
        method: "POST",
        body: JSON.stringify({ inputs, steps }),
      });
      setResult(out);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="page-header flex justify-between items-center">
        <div>
          <div className="page-header-eyebrow">AIP Platform</div>
          <h1 className="page-header-title">AIP Logic Canvas</h1>
          <p className="text-xs text-gray-500 mt-1">
            Build and chain LLM, SQL, and transformation nodes visually.
          </p>
        </div>
        <div>
          <button
            onClick={handleRunChain}
            disabled={running}
            className="btn-primary px-4 py-2 disabled:opacity-50 text-sm font-semibold"
          >
            {running ? "Running Canvas..." : "Execute Logic Chain"}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100vh-220px)]">
        {/* Left: Input Variables */}
        <div className="lg:col-span-1 flex flex-col app-card overflow-hidden">
          <div className="section-header">
            1. Input Parameters
          </div>
          <div className="p-4 flex-1 overflow-y-auto space-y-4">
            <div className="space-y-2">
              {Object.entries(inputs).map(([key, val]) => (
                <div key={key} className="app-card p-2 flex flex-col gap-1 relative group">
                  <button
                    onClick={() => handleRemoveInput(key)}
                    className="absolute top-2 right-2 text-gray-400 hover:text-red-500 text-xs font-bold transition-colors"
                  >
                    Remove
                  </button>
                  <span className="text-[10px] font-mono font-bold text-blue-600">{"{{"}inputs.{key}{"}}"}</span>
                  <span className="text-xs text-gray-850 font-semibold">{val}</span>
                </div>
              ))}
            </div>

            {/* Add Input Form */}
            <div className="border-t border-gray-100 pt-3 space-y-2">
              <span className="text-[10px] text-gray-400 font-bold block">Add Parameter</span>
              <input
                type="text"
                placeholder="Parameter key"
                value={newInputKey}
                onChange={(e) => setNewInputKey(e.target.value)}
                className="w-full px-2.5 py-1.5 border rounded-lg text-xs"
              />
              <input
                type="text"
                placeholder="Parameter value"
                value={newInputValue}
                onChange={(e) => setNewInputValue(e.target.value)}
                className="w-full px-2.5 py-1.5 border rounded-lg text-xs"
              />
              <button
                onClick={handleAddInput}
                className="btn-ghost w-full px-3 py-1.5 text-xs font-bold"
              >
                Add Parameter
              </button>
            </div>
          </div>
        </div>

        {/* Center: Logic steps list */}
        <div className="lg:col-span-2 flex flex-col app-card overflow-hidden">
          <div className="section-header flex items-center justify-between">
            <span className="section-header-title">2. Execution Nodes</span>
            <button
              onClick={() => setShowAddStep(true)}
              className="btn-primary px-2 py-1 text-xs font-semibold"
            >
              + Add Node
            </button>
          </div>

          <div className="p-4 flex-1 overflow-y-auto space-y-6 flex flex-col items-center">
            {steps.map((step, idx) => (
              <div key={idx} className="w-full relative flex flex-col items-center">
                {idx > 0 && (
                  <div className="h-6 w-0.5 bg-blue-200 mb-2 relative">
                    <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-[9px] text-blue-500 font-bold">▼</span>
                  </div>
                )}
                
                <div className="app-card p-4 w-full relative group hover:border-blue-300 transition-all">
                  <button
                    onClick={() => handleRemoveStep(idx)}
                    className="absolute top-3 right-3 text-gray-400 hover:text-red-500 font-bold text-sm"
                  >
                    &times;
                  </button>

                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 uppercase tracking-wider">
                      {step.type}
                    </span>
                    <span className="text-xs text-gray-400 font-bold">Outputs to</span>
                    <span className="text-xs font-mono font-bold border px-1.5 py-0.5 rounded" style={{ background: "var(--panel-2)" }}>
                      {"{{"}steps.{step.output_var}{"}}"}
                    </span>
                  </div>

                  <p className="text-xs font-mono p-2.5 border rounded-lg whitespace-pre-wrap" style={{ background: "var(--panel-2)", color: "var(--text)" }}>
                    {step.prompt || step.query || step.template}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Outputs & Run logs */}
        <div className="lg:col-span-1 flex flex-col app-card overflow-hidden">
          <div className="section-header">
            3. Run Results
          </div>
          <div className="p-4 flex-1 overflow-y-auto space-y-4 font-mono text-xs">
            {error && (
              <div className="p-3 bg-red-50 border border-red-100 text-red-650 rounded-lg whitespace-pre-wrap">
                <strong>Execution Failed:</strong>{"\n"}{error}
              </div>
            )}

            {result && (
              <div className="space-y-4">
                <div className="p-3 bg-green-50 border border-green-150 text-green-700 rounded-lg font-sans">
                  <strong>Success!</strong> Logic chain executed.
                </div>

                <div className="space-y-3">
                  {result.execution_log?.map((log: any, idx: number) => (
                    <div key={idx} className="p-2.5 bg-gray-50 border border-gray-200 rounded-lg space-y-1">
                      <div className="flex justify-between items-center text-[10px] border-b pb-1 mb-1 font-sans">
                        <strong className="uppercase text-blue-600">{log.type}</strong>
                        <span className="text-gray-400">steps.{log.output_var}</span>
                      </div>
                      <div className="text-gray-800 whitespace-pre-wrap break-all text-[11px]">
                        {typeof log.output === "object" ? JSON.stringify(log.output, null, 2) : String(log.output)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!error && !result && (
              <div className="h-full flex items-center justify-center text-gray-450 text-center font-sans">
                Click &quot;Execute Logic Chain&quot; to run the nodes.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Add Step Modal */}
      {showAddStep && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="app-card rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
            <div className="section-header flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900">Add Canvas Node</h3>
              <button onClick={() => setShowAddStep(false)} className="text-gray-400 hover:text-gray-600 text-xl font-medium">&times;</button>
            </div>

            <form onSubmit={handleAddStep}>
              <div className="p-6 space-y-4">
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-bold text-gray-600">Node Type</label>
                  <select
                    value={newStepType}
                    onChange={(e: any) => setNewStepType(e.target.value)}
                    className="input-dark px-3 py-1.5 text-sm"
                  >
                    <option value="llm">LLM Prompt Block</option>
                    <option value="template">Template Substitutor</option>
                    <option value="sql">SQL Execution Block</option>
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-bold text-gray-600">Output Variable Name</label>
                  <input
                    type="text"
                    value={newStepVar}
                    onChange={(e) => setNewStepVar(e.target.value)}
                    placeholder="e.g. client_sentiment"
                    className="px-3 py-1.5 border rounded-lg text-sm"
                    required
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-xs font-bold text-gray-600">Content / Prompt / Template / SQL</label>
                  <textarea
                    value={newStepContent}
                    onChange={(e) => setNewStepContent(e.target.value)}
                    placeholder="Use {{inputs.var}} or {{steps.var}} to bind parameters."
                    rows={4}
                    className="px-3 py-1.5 border rounded-lg text-sm font-mono"
                    required
                  />
                </div>
              </div>

              <div className="px-6 py-4 flex items-center justify-end gap-3" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)" }}>
                <button
                  type="button"
                  onClick={() => setShowAddStep(false)}
                  className="btn-ghost px-4 py-2 text-sm font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-primary px-4 py-2 text-sm font-semibold"
                >
                  Add Node
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
