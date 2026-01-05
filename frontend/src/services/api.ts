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
