const API_BASE = "/api";

export interface Group {
    name: string;
    players: string[];
}

export interface Availability {
    group_name: string;
    user_name: string;
    date: string; // ISO date string YYYY-MM-DD
    status: string; // "Available" | "Maybe" | "No"
}

export async function fetchGroups(): Promise<Group[]> {
    const res = await fetch(`${API_BASE}/groups`);
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
}

export async function fetchAvailability(group: string, year: number, month: number): Promise<Availability[]> {
    const res = await fetch(`${API_BASE}/availability/${group}/${year}/${month}?t=${new Date().getTime()}`);
    if (!res.ok) throw new Error("Failed to fetch availability");
    return res.json();
}

export async function updateAvailability(group: string, user: string, date: string, status: string | null) {
    const res = await fetch(`${API_BASE}/availability`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group, user, date, status }),
    });
    if (!res.ok) throw new Error("Failed to update availability");
    return res.json();
}



export async function fetchAllAvailability(start: string, end: string): Promise<Availability[]> {
    const res = await fetch(`${API_BASE}/admin/all-availability?start=${start}&end=${end}`);
    if (!res.ok) throw new Error("Failed to fetch all availability");
    return res.json();
}

export interface AccountInfo {
    id: string;
    email: string | null;
    username: string | null;
    display_name: string | null;
}

export interface MyGroup {
    id: string;
    name: string;
    timezone: string;
    role: string;
    member_count: number;
}

export interface GroupMember {
    id: string;
    display_name: string;
    role: string;
    display_order: number;
}

export interface GroupDetail {
    id: string;
    name: string;
    timezone: string;
    role: string;
    current_user_id: string;
    members: GroupMember[];
}

export interface ConfirmedSession {
    id: string;
    group_id: string;
    day: string;
    confirmed_by_user_id: string;
    confirmed_at: string;
}

export interface MyConfirmedSession extends ConfirmedSession {
    group_name: string;
}

export async function fetchCurrentAccount(token?: string | null): Promise<AccountInfo> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/me`, { headers });
    if (!res.ok) throw new Error("Failed to fetch account info");
    return res.json();
}

export async function fetchMyGroups(token?: string | null): Promise<MyGroup[]> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/me/groups`, { headers });
    if (!res.ok) throw new Error("Failed to fetch user groups");
    return res.json();
}

export async function fetchGroupDetail(groupId: string, token?: string | null): Promise<GroupDetail> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}`, { headers });
    if (!res.ok) throw new Error("Failed to fetch group details");
    return res.json();
}

export async function fetchGroupMonthAvailability(
    groupId: string,
    year: number,
    month: number,
    token?: string | null
): Promise<Availability[]> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}/availability/${year}/${month}?t=${new Date().getTime()}`, {
        headers,
    });
    if (!res.ok) throw new Error("Failed to fetch group availability");
    return res.json();
}

export async function updateGroupAvailability(
    groupId: string,
    date: string,
    status: string | null,
    token?: string | null
): Promise<{ status: string; new_state: string | null }> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}/availability`, {
        method: "POST",
        headers,
        body: JSON.stringify({ date, status }),
    });
    if (!res.ok) throw new Error("Failed to update availability");
    return res.json();
}

export async function fetchGroupAdminAvailability(
    groupId: string,
    start: string,
    end: string,
    token?: string | null
): Promise<Availability[]> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}/admin/availability?start=${start}&end=${end}`, {
        headers,
    });
    if (!res.ok) throw new Error("Failed to fetch group admin availability");
    return res.json();
}

export async function fetchGroupConfirmedSessions(
    groupId: string,
    start: string,
    end: string,
    token?: string | null
): Promise<ConfirmedSession[]> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(
        `${API_BASE}/groups/${groupId}/confirmed-sessions?start=${start}&end=${end}`,
        { headers }
    );
    if (!res.ok) throw new Error("Failed to fetch confirmed sessions");
    return res.json();
}

export async function fetchMyConfirmedSessions(
    start: string,
    end: string,
    token?: string | null
): Promise<MyConfirmedSession[]> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(
        `${API_BASE}/me/confirmed-sessions?start=${start}&end=${end}`,
        { headers }
    );
    if (!res.ok) throw new Error("Failed to fetch your confirmed sessions");
    return res.json();
}

export async function confirmGroupSession(
    groupId: string,
    day: string,
    token?: string | null
): Promise<ConfirmedSession> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}/confirmed-sessions/${day}`, {
        method: "PUT",
        headers,
    });
    if (!res.ok) throw new Error("Failed to confirm session");
    return res.json();
}

export async function cancelGroupSession(
    groupId: string,
    day: string,
    token?: string | null
): Promise<{ status: string }> {
    const headers: Record<string, string> = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`${API_BASE}/groups/${groupId}/confirmed-sessions/${day}`, {
        method: "DELETE",
        headers,
    });
    if (!res.ok) throw new Error("Failed to cancel confirmed session");
    return res.json();
}
