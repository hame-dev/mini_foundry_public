"use client";
import { createContext, useCallback, useContext, useState } from "react";

type VariableValue = Record<string, unknown> | string | number | null;

interface DashboardVariablesContextValue {
  variables: Record<string, VariableValue>;
  setVariable: (name: string, value: VariableValue) => void;
  getVariable: (name: string) => VariableValue;
  resolveTemplate: (template: string) => string;
}

const DashboardVariablesContext = createContext<DashboardVariablesContextValue>({
  variables: {},
  setVariable: () => {},
  getVariable: () => null,
  resolveTemplate: (t) => t,
});

export function DashboardVariablesProvider({
  children,
  initialVariables = {},
}: {
  children: React.ReactNode;
  initialVariables?: Record<string, VariableValue>;
}) {
  const [variables, setVariables] = useState<Record<string, VariableValue>>(initialVariables);

  const setVariable = useCallback((name: string, value: VariableValue) => {
    setVariables((prev) => ({ ...prev, [name]: value }));
  }, []);

  const getVariable = useCallback(
    (name: string): VariableValue => variables[name] ?? null,
    [variables]
  );

  /**
   * Replace {{variables.name.field}} and {{variables.name}} tokens in a
   * template string with the current variable values.
   */
  const resolveTemplate = useCallback(
    (template: string): string => {
      return template.replace(/\{\{variables\.([^}]+)\}\}/g, (_, path) => {
        const parts = path.split(".");
        const varName = parts[0];
        const fieldPath = parts.slice(1);
        let val: unknown = variables[varName];
        for (const field of fieldPath) {
          if (val && typeof val === "object" && !Array.isArray(val)) {
            val = (val as Record<string, unknown>)[field];
          } else {
            val = undefined;
            break;
          }
        }
        return val != null ? String(val) : "";
      });
    },
    [variables]
  );

  return (
    <DashboardVariablesContext.Provider value={{ variables, setVariable, getVariable, resolveTemplate }}>
      {children}
    </DashboardVariablesContext.Provider>
  );
}

export function useDashboardVariable(name: string) {
  const ctx = useContext(DashboardVariablesContext);
  return [ctx.getVariable(name), (v: VariableValue) => ctx.setVariable(name, v)] as const;
}

export function useDashboardVariables() {
  return useContext(DashboardVariablesContext);
}
