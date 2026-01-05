"use client";

import { useEffect, useState } from "react";
import { format, addMonths, subMonths } from "date-fns";
import { fetchGroups, fetchAvailability, updateAvailability, Group, Availability } from "@/services/api";
import { CalendarGrid } from "@/components/CalendarGrid";
import { ChevronLeft, ChevronRight } from "lucide-react";
import clsx from "clsx";

export default function Home() {
    const [groups, setGroups] = useState<Group[]>([]);
    const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
    const [currentUser, setCurrentUser] = useState<string | null>(null);
    const [currentDate, setCurrentDate] = useState(new Date());
    const [availability, setAvailability] = useState<Availability[]>([]);

    // -- Load Groups --
    useEffect(() => {
        fetchGroups().then(data => {
            setGroups(data);
            if (data.length > 0) {
                setSelectedGroup(data[0].name);
            }
        });
    }, []);

    // -- Load Availability --
    useEffect(() => {
        if (!selectedGroup) return;
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth() + 1;
        fetchAvailability(selectedGroup, year, month).then(setAvailability);
    }, [selectedGroup, currentDate]);

    // -- Handlers --
    const handleToggleStatus = async (date: Date) => {
        if (!selectedGroup || !currentUser) {
            alert("Please select a user first!");
            return;
        }

        const dateStr = format(date, "yyyy-MM-dd");
        const currentStatus = availability.find(
            a => a.date === dateStr && a.user_name === currentUser
        )?.status;

        let nextStatus: string | null = "Available";
        if (currentStatus === "Available") nextStatus = "Maybe";
        else if (currentStatus === "Maybe") nextStatus = "No";
        else if (currentStatus === "No") nextStatus = null;

        // Optimistic update
        const newEntry: Availability = { group_name: selectedGroup, user_name: currentUser, date: dateStr, status: nextStatus || "" };
        const others = availability.filter(a => !(a.date === dateStr && a.user_name === currentUser));

        if (nextStatus) {
            setAvailability([...others, newEntry]);
        } else {
            setAvailability(others);
        }

        await updateAvailability(selectedGroup, currentUser, dateStr, nextStatus);
    };

    const currentGroupPlayers = groups.find(g => g.name === selectedGroup)?.players || [];
    const maxPlayers = currentGroupPlayers.length;

    return (
        <div className="flex min-h-screen bg-white text-gray-900 font-sans">

            {/* SIDEBAR */}
            <aside className="w-[300px] border-r border-gray-200 bg-gray-50 p-6 pt-10 flex flex-col shrink-0">
                <div className="mb-8">
                    <h2 className="text-xl font-bold mb-4 flex items-center gap-2 text-gray-800">
                        <span>🧭</span> Navigation
                    </h2>

                    <div className="mb-6 space-y-2">
                        <label className="text-sm font-semibold text-gray-600 block">
                            Who are you?
                        </label>
                        <select
                            className="w-full border border-gray-300 rounded-md p-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                            value={currentUser || ""}
                            onChange={(e) => setCurrentUser(e.target.value || null)}
                        >
                            <option value="">Select identity...</option>
                            {groups.map(g => (
                                <optgroup key={g.name} label={`--- ${g.name} ---`}>
                                    {g.players.map(p => (
                                        <option key={p} value={p}>{p}</option>
                                    ))}
                                </optgroup>
                            ))}
                        </select>
                    </div>

                    <hr className="my-4 border-gray-200" />

                    {currentUser && (
                        <div className="bg-green-50 text-green-700 px-4 py-3 rounded text-sm font-medium border border-green-200">
                            Logged in as <span className="font-bold">{currentUser}</span>
                        </div>
                    )}

                    <div className="mt-4 text-xs text-gray-500 font-mono">
                        {selectedGroup ? `Member of ${selectedGroup}` : "No group selected"}
                    </div>
                </div>
            </aside>

            {/* MAIN CONTENT */}
            <main className="flex-1 p-10 overflow-y-auto bg-white">
                <div className="max-w-[1400px]">

                    {/* HEADER */}
                    <header className="mb-10">
                        <h1 className="text-3xl font-bold flex items-center gap-3 mb-6 tracking-tight text-gray-900">
                            <span className="text-4xl">🎲</span> DnD Planner {selectedGroup ? `- ${selectedGroup}` : ""}
                        </h1>

                        {/* DATE CONTROLS */}
                        <div className="flex items-end gap-4">
                            <div className="flex items-center gap-2 bg-gray-100 border border-gray-200 rounded-md p-1">
                                <button className="p-2 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(subMonths(currentDate, 12))}>&laquo;</button>
                                <span className="font-mono text-sm px-2 text-gray-700">{format(currentDate, 'yyyy')}</span>
                                <button className="p-2 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(addMonths(currentDate, 12))}>&raquo;</button>
                            </div>

                            <div className="flex items-center gap-2 bg-gray-100 border border-gray-200 rounded-md p-1 min-w-[160px] justify-between px-2">
                                <span className="font-medium text-sm text-gray-800">{format(currentDate, "MMMM")}</span>
                                <div className="flex">
                                    <button className="p-1 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(subMonths(currentDate, 1))}><ChevronLeft size={16} /></button>
                                    <button className="p-1 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(addMonths(currentDate, 1))}><ChevronRight size={16} /></button>
                                </div>
                            </div>
                        </div>
                    </header>

                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">

                        {/* LEFT: Personal Availability */}
                        <section className={clsx("transition-all duration-300", !currentUser ? "opacity-40 pointer-events-none blur-[1px]" : "")}>
                            <div className="border border-gray-200 rounded-lg shadow-sm bg-white overflow-hidden">
                                <div className="p-6 border-b border-gray-100">
                                    <h3 className="text-lg font-semibold flex items-center gap-2 text-gray-900">
                                        🗓️ {currentUser ? `${currentUser}'s Availability` : "Your Availability"}
                                    </h3>
                                    <p className="text-sm text-gray-500 mt-1">Click dates to toggle your status</p>
                                </div>
                                <div className="p-6">
                                    <CalendarGrid
                                        currentDate={currentDate}
                                        availability={availability.filter(a => a.user_name === currentUser)}
                                        maxPlayers={1} // Self
                                        onDateClick={handleToggleStatus}
                                        renderCell={(date, stats) => {
                                            const status = stats[0]?.status;
                                            return (
                                                <div className="flex-1 flex items-center justify-center">
                                                    {status === 'Available' && <span className="text-2xl">✅</span>}
                                                    {status === 'Maybe' && <span className="text-2xl text-yellow-500">❓</span>}
                                                    {status === 'No' && <span className="text-2xl text-red-500">✕</span>}
                                                </div>
                                            )
                                        }}
                                    />
                                    <div className="mt-4 flex items-center gap-3 text-sm text-gray-500 justify-center">
                                        <span>Cycle: ⬜ → ✅ → <span className="text-yellow-500">❓</span> → <span className="text-red-500">✕</span></span>
                                    </div>
                                </div>
                            </div>
                        </section>

                        {/* RIGHT: Team Overview */}
                        <section>
                            <div className="border border-gray-200 rounded-lg shadow-sm bg-white overflow-hidden">
                                <div className="p-6 border-b border-gray-100">
                                    <h3 className="text-lg font-semibold flex items-center gap-2 text-gray-900">⚔️ Team Overview</h3>
                                    <p className="text-sm text-gray-500 mt-1">See when everyone else is free</p>
                                </div>
                                <div className="p-6">
                                    <CalendarGrid
                                        currentDate={currentDate}
                                        availability={availability}
                                        maxPlayers={maxPlayers}
                                        onDateClick={() => { }} // Read only
                                    />
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </main>
        </div>
    );
}
