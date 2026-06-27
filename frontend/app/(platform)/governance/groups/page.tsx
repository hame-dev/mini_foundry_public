"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import {
  addGroupMember,
  createGroup,
  GovernanceGroup,
  GovernanceGroupMember,
  listGroupMembers,
  listGroups,
  removeGroupMember,
} from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceGroupsPage() {
  const [groups, setGroups] = useState<GovernanceGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [members, setMembers] = useState<GovernanceGroupMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [membersLoading, setMembersLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [groupName, setGroupName] = useState("");
  const [description, setDescription] = useState("");
  const [memberUserId, setMemberUserId] = useState("");

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? groups[0] ?? null,
    [groups, selectedGroupId],
  );

  const loadGroups = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const rows = await listGroups();
      setGroups(rows);
      setSelectedGroupId((current) => current ?? rows[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load groups.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMembers = useCallback(async (groupId: string) => {
    setMembersLoading(true);
    setError(null);
    try {
      const data = await listGroupMembers(groupId);
      setMembers(data.members);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load group members.");
    } finally {
      setMembersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  useEffect(() => {
    if (selectedGroup?.id) {
      void loadMembers(selectedGroup.id);
    } else {
      setMembers([]);
    }
  }, [loadMembers, selectedGroup?.id]);

  async function handleCreateGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const group = await createGroup({ name: groupName.trim(), description: description.trim() || null });
      setGroupName("");
      setDescription("");
      await loadGroups();
      setSelectedGroupId(group.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create group.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGroup || !memberUserId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await addGroupMember(selectedGroup.id, memberUserId.trim());
      setMemberUserId("");
      await Promise.all([loadGroups(), loadMembers(selectedGroup.id)]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to add member.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!selectedGroup) return;
    setSaving(true);
    setError(null);
    try {
      await removeGroupMember(selectedGroup.id, userId);
      await Promise.all([loadGroups(), loadMembers(selectedGroup.id)]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to remove member.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Groups" type="Governance" status={`${groups.length} groups`} />
      {loading ? <LoadingState label="Loading governance groups..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Group directory</h2>
              <p className="text-sm text-[var(--muted)]">Groups are principals for inherited resource ACLs and marking eligibility.</p>
            </div>
            {groups.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Members</th>
                      <th className="px-4 py-3">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((group) => (
                      <tr
                        key={group.id}
                        className={`cursor-pointer border-t border-[var(--line-soft)] hover:bg-[var(--panel-2)] ${
                          selectedGroup?.id === group.id ? "bg-[var(--panel-2)]" : ""
                        }`}
                        onClick={() => setSelectedGroupId(group.id)}
                      >
                        <td className="px-4 py-3">
                          <div className="font-medium">{group.name}</div>
                          <div className="text-xs text-[var(--muted)]">{group.description || "No description"}</div>
                        </td>
                        <td className="px-4 py-3">{group.member_count}</td>
                        <td className="px-4 py-3 text-[var(--muted)]">{new Date(group.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-4">
                <EmptyState title="No groups" detail="Create a group to grant shared permissions and marking eligibility." />
              </div>
            )}
          </section>

          <aside className="space-y-4">
            <form className="app-card space-y-3 p-4" onSubmit={handleCreateGroup}>
              <h2 className="font-semibold">Create group</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={groupName} onChange={(event) => setGroupName(event.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <textarea className="input-dark mt-1 min-h-20 w-full" value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !groupName.trim()}>
                {saving ? "Saving" : "Create group"}
              </button>
            </form>

            <section className="app-card p-4">
              <h2 className="font-semibold">{selectedGroup ? `${selectedGroup.name} members` : "Members"}</h2>
              {selectedGroup ? (
                <>
                  <form className="mt-3 flex gap-2" onSubmit={handleAddMember}>
                    <input
                      className="input-dark min-w-0 flex-1"
                      placeholder="User ID"
                      value={memberUserId}
                      onChange={(event) => setMemberUserId(event.target.value)}
                    />
                    <button type="submit" className="toolbar-button" disabled={saving || !memberUserId.trim()}>
                      Add
                    </button>
                  </form>
                  {membersLoading ? <LoadingState label="Loading members..." /> : null}
                  <div className="mt-3 space-y-2">
                    {members.map((member) => (
                      <div key={member.id} className="flex items-center justify-between gap-3 rounded border border-[var(--line-soft)] bg-[var(--panel-2)] p-3 text-sm">
                        <div className="min-w-0">
                          <div className="truncate font-medium">{member.name || member.email}</div>
                          <div className="truncate text-xs text-[var(--muted)]">{member.email}</div>
                        </div>
                        <button type="button" className="toolbar-button" disabled={saving} onClick={() => void handleRemoveMember(member.id)}>
                          Remove
                        </button>
                      </div>
                    ))}
                    {!membersLoading && !members.length ? (
                      <p className="text-sm text-[var(--muted)]">No members assigned to this group.</p>
                    ) : null}
                  </div>
                </>
              ) : (
                <p className="mt-2 text-sm text-[var(--muted)]">Select or create a group to manage members.</p>
              )}
            </section>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
