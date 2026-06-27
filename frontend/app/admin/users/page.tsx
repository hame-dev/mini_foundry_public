"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type UserRow = {
  id: string;
  email: string;
  name: string | null;
  is_active: boolean;
  roles: string[];
  created_at: string;
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoles, setNewRoles] = useState("analyst");

  function load() {
    apiFetch<UserRow[]>("/admin/users").then(setUsers).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email: newEmail,
          password: newPassword,
          roles: newRoles.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      setNewEmail(""); setNewPassword(""); setNewRoles("analyst"); load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Users</h1>
      {error && <div className="text-red-600 text-sm">{error}</div>}

      <form onSubmit={create} className="app-card p-4 grid grid-cols-4 gap-2 items-end">
        <div>
          <label className="block text-xs mb-1">Email</label>
          <input className="input-dark w-full" value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)} required type="email" />
        </div>
        <div>
          <label className="block text-xs mb-1">Password</label>
          <input className="input-dark w-full" value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)} required type="password" />
        </div>
        <div>
          <label className="block text-xs mb-1">Roles (csv)</label>
          <input className="input-dark w-full" value={newRoles}
            onChange={(e) => setNewRoles(e.target.value)} />
        </div>
        <button className="btn-primary text-sm py-1">Create</button>
      </form>

      <div className="app-card overflow-hidden">
      <table className="data-table">
        <thead>
          <tr>
            <th className="px-4 py-2">Email</th>
            <th className="px-4 py-2">Name</th>
            <th className="px-4 py-2">Roles</th>
            <th className="px-4 py-2">Active</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-t">
              <td className="px-4 py-2">{u.email}</td>
              <td className="px-4 py-2">{u.name ?? "—"}</td>
              <td className="px-4 py-2 text-xs">{u.roles.join(", ") || "—"}</td>
              <td className="px-4 py-2">{u.is_active ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
