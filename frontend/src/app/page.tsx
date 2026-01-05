"use client";

import { useEffect, useState } from "react";
import { format, addMonths, subMonths, startOfMonth, endOfMonth } from "date-fns";
import { fetchGroups, fetchAvailability, updateAvailability, generateTestData, fetchAllAvailability, Group, Availability } from "@/services/api";
import { CalendarGrid } from "@/components/CalendarGrid";
import { ChevronLeft, ChevronRight, Menu, X } from "lucide-react";
import clsx from "clsx";

type ViewMode = "PLAYER" | "ADMIN_GHOST" | "ADMIN_CROSS" | "ADMIN_ONESHOT" | "ADMIN_PERSONAL";

export default function Home() {
    // -- Data State --
    const [groups, setGroups] = useState<Group[]>([]);
    const [allAvailability, setAllAvailability] = useState<Availability[]>([]); // For Admin views

    // -- Selection State --
    const [currentUser, setCurrentUser] = useState<string | null>(null);
    const [viewMode, setViewMode] = useState<ViewMode>("PLAYER");
    const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);

    // -- Admin Specific State --
    const [ghostUser, setGhostUser] = useState<string | null>(null);
    const [crossGroup1, setCrossGroup1] = useState<string | null>(null);
    const [crossGroup2, setCrossGroup2] = useState<string | null>(null);

    // -- Context Menu State --
    const [contextMenu, setContextMenu] = useState<{ isOpen: boolean, x: number, y: number, date: Date | null }>({
        isOpen: false, x: 0, y: 0, date: null
    });

    // -- Day Details Modal State --
    const [dateDetails, setDateDetails] = useState<{ isOpen: boolean, date: Date | null }>({ isOpen: false, date: null });

    // -- Calendar State --
    const [currentDate, setCurrentDate] = useState(new Date());
    const [availability, setAvailability] = useState<Availability[]>([]);

    // -- Load Groups --
    useEffect(() => {
        fetchGroups().then(data => {
            setGroups(data);
            if (data.length > 0) {
                // Default selection logic if needed
                setCrossGroup1(data[0].name);
                if (data.length > 1) setCrossGroup2(data[1].name);
            }
        });
    }, []);

    // -- Mode Switcher Logic --
    useEffect(() => {
        if (currentUser === "Admin") {
            setViewMode("ADMIN_PERSONAL");
            setSelectedGroup("Admin");
        } else if (currentUser) {
            setViewMode("PLAYER");
            // Auto-select group for regular user
            const usersGroup = groups.find(g => g.players.includes(currentUser));
            if (usersGroup) setSelectedGroup(usersGroup.name);
        } else {
            setSelectedGroup(null);
        }
    }, [currentUser, groups]);

    // -- Load Availability --
    useEffect(() => {
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth() + 1;

        if (viewMode === "ADMIN_CROSS" || viewMode === "ADMIN_ONESHOT") {
            // Load ALL data for the month
            const start = format(startOfMonth(currentDate), "yyyy-MM-dd");
            const end = format(endOfMonth(currentDate), "yyyy-MM-dd");
            fetchAllAvailability(start, end).then(setAllAvailability);
        } else if (selectedGroup) {
            fetchAvailability(selectedGroup, year, month).then(setAvailability);
        }
    }, [selectedGroup, currentDate, viewMode]);


    // -- Handlers --
    const handleToggleStatus = async (date: Date) => {
        const targetUser = viewMode === "ADMIN_GHOST" ? ghostUser : currentUser;
        const targetGroup = selectedGroup;

        if (!targetGroup || !targetUser) {
            alert("Please select a user first!");
            return;
        }

        const dateStr = format(date, "yyyy-MM-dd");
        const currentData = availability;

        const currentStatus = currentData.find(
            a => a.date === dateStr && a.user_name === targetUser
        )?.status;

        let nextStatus: string | null = "Available";
        if (currentStatus === "Available") nextStatus = "Maybe";
        else if (currentStatus === "Maybe") nextStatus = "No";
        else if (currentStatus === "No") nextStatus = null;

        // Optimistic update
        const newEntry: Availability = { group_name: targetGroup, user_name: targetUser, date: dateStr, status: nextStatus || "" };
        const others = currentData.filter(a => !(a.date === dateStr && a.user_name === targetUser));

        const nextList = nextStatus ? [...others, newEntry] : others;
        setAvailability(nextList);

        await updateAvailability(targetGroup, targetUser, dateStr, nextStatus);
    };

    const handleGenerateData = async () => {
        if (confirm("This will overwrite data for this month. Continue?")) {
            await generateTestData(currentDate.getFullYear(), currentDate.getMonth() + 1);
            alert("Data generated! Please refresh/toggle month to reload.");
            // Trigger reload
            const year = currentDate.getFullYear();
            const month = currentDate.getMonth() + 1;
            if (selectedGroup) {
                const promises = [fetchAvailability(selectedGroup, year, month)];
                if (selectedGroup !== "Admin") {
                    promises.push(fetchAvailability("Admin", year, month));
                }
                Promise.all(promises).then((results) => {
                    setAvailability(results.flat());
                });
            }
        }
    }

    const handleContextMenu = (date: Date, e: React.MouseEvent) => {
        setContextMenu({
            isOpen: true,
            x: e.pageX,
            y: e.pageY,
            date: date
        });
    };

    const handleQuickStatus = async (status: string | null) => {
        if (!contextMenu.date) return;

        const targetUser = viewMode === "ADMIN_GHOST" ? ghostUser : currentUser;
        const targetGroup = selectedGroup;

        if (!targetGroup || !targetUser) {
            alert("Please select a user first!");
            setContextMenu({ ...contextMenu, isOpen: false });
            return;
        }

        const dateStr = format(contextMenu.date, "yyyy-MM-dd");

        // Optimistic update
        const newEntry: Availability = { group_name: targetGroup, user_name: targetUser, date: dateStr, status: status || "" };
        const others = availability.filter(a => !(a.date === dateStr && a.user_name === targetUser));
        const nextList = status ? [...others, newEntry] : others;

        setAvailability(nextList);
        setContextMenu({ ...contextMenu, isOpen: false });

        await updateAvailability(targetGroup, targetUser, dateStr, status);
    };

    const openDateDetails = (date: Date) => {
        setDateDetails({ isOpen: true, date });
    };

    // -- Derived Data --
    const rawGroupPlayers = groups.find(g => g.name === selectedGroup)?.players || [];
    // Always include Admin (DM) in the group view, unless we are specifically in Admin view (which is its own group)
    const currentGroupPlayers = selectedGroup === "Admin" ? ["Admin"] : [...rawGroupPlayers, "Admin"];

    const maxPlayers = currentGroupPlayers.length;

    // Helper for OneShot view
    const getOneshotMatches = (): { date: Date, hostFull: boolean, guests: string[] }[] => {
        if (!allAvailability.length || !crossGroup1 || !crossGroup2) return [];

        const matches = [];
        const days = startOfMonth(currentDate);
        const lastDay = endOfMonth(currentDate);

        const hostGroupObj = groups.find(g => g.name === crossGroup1);
        if (!hostGroupObj) return [];
        const hostSize = hostGroupObj.players.length;

        for (let d = new Date(days); d <= lastDay; d.setDate(d.getDate() + 1)) {
            const dStr = format(d, "yyyy-MM-dd");
            const dayStats = allAvailability.filter(a => a.date === dStr);

            const hostAvailable = dayStats.filter(a => a.group_name === crossGroup1 && a.status === 'Available').length;

            if (hostAvailable === hostSize) {
                const guests = dayStats
                    .filter(a => a.group_name === crossGroup2 && (a.status === 'Available' || a.status === 'Maybe'))
                    .map(a => a.user_name);

                if (guests.length > 0) {
                    matches.push({ date: new Date(d), hostFull: true, guests });
                }
            }
        }
        return matches;
    }

    return (
        <div className="flex min-h-screen bg-white text-gray-900 font-sans">

            {/* SIDEBAR */}
            <aside
                className={clsx(
                    "border-r border-gray-200 bg-gray-50 flex flex-col shrink-0 transition-all duration-300 relative",
                    isSidebarOpen ? "w-[300px] p-6 pt-10" : "w-[0px] p-0"
                )}
            >
                <button
                    onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                    className={clsx(
                        "absolute top-6 bg-white border border-gray-200 rounded-full p-2 shadow-md hover:bg-gray-100 z-50 cursor-pointer transition-all duration-300",
                        isSidebarOpen ? "-right-3" : "-right-12 border-l-4 border-l-blue-500"
                    )}
                    title={isSidebarOpen ? "Collapse Sidebar" : "Expand Sidebar"}
                >
                    {isSidebarOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
                </button>

                <div className={clsx("transition-opacity duration-200 delay-100", isSidebarOpen ? "opacity-100" : "opacity-0 hidden")}>
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
                                <option value="Admin" className="font-bold">--- SYSTEM ---</option>
                                <option value="Admin">🛠️ Admin</option>
                                {groups.map(g => (
                                    <optgroup key={g.name} label={`--- ${g.name} ---`}>
                                        {g.players.map(p => (
                                            <option key={p} value={p}>{p}</option>
                                        ))}
                                    </optgroup>
                                ))}
                            </select>
                        </div>

                        {currentUser === "Admin" && (
                            <div className="mt-6 border-t pt-4 border-gray-300 space-y-4">
                                <h3 className="text-sm font-bold text-gray-500 uppercase">Admin Controls</h3>

                                <div className="flex flex-col gap-2">
                                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                                        <input type="radio" checked={viewMode === "PLAYER"} onChange={() => { setViewMode("PLAYER"); setSelectedGroup(groups[0]?.name || null); }} />
                                        <span>Player View (Ghost)</span>
                                    </label>
                                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                                        <input type="radio" checked={viewMode === "ADMIN_CROSS"} onChange={() => setViewMode("ADMIN_CROSS")} />
                                        <span>Cross-Group Overview</span>
                                    </label>
                                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                                        <input type="radio" checked={viewMode === "ADMIN_ONESHOT"} onChange={() => setViewMode("ADMIN_ONESHOT")} />
                                        <span>Oneshot Recruiter</span>
                                    </label>
                                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                                        <input type="radio" checked={viewMode === "ADMIN_PERSONAL"} onChange={() => { setViewMode("ADMIN_PERSONAL"); setSelectedGroup("Admin"); }} />
                                        <span>Admin Availability</span>
                                    </label>
                                </div>

                                <hr />

                                {viewMode === "PLAYER" && (
                                    <div className="bg-gray-200 p-3 rounded text-sm space-y-2">
                                        <h4 className="font-bold">👤 Ghost Login</h4>
                                        <select
                                            className="w-full p-1 text-xs rounded border"
                                            value={selectedGroup || ""}
                                            onChange={e => setSelectedGroup(e.target.value)}
                                        >
                                            {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                        </select>
                                        <select
                                            className="w-full p-1 text-xs rounded border"
                                            value={ghostUser || ""}
                                            onChange={e => setGhostUser(e.target.value)}
                                        >
                                            <option value="">Simulate User...</option>
                                            {groups.find(g => g.name === selectedGroup)?.players.map(p => (
                                                <option key={p} value={p}>{p}</option>
                                            ))}
                                        </select>
                                        {ghostUser && <div className="text-xs text-blue-600">Viewing as: <b>{ghostUser}</b></div>}
                                    </div>
                                )}

                                <button
                                    onClick={handleGenerateData}
                                    className="w-full bg-red-100 text-red-700 hover:bg-red-200 text-xs py-2 rounded font-bold border border-red-300"
                                >
                                    ⚡ Generate Test Data
                                </button>
                            </div>
                        )}

                        {!currentUser && <div className="mt-8 text-sm text-gray-500 italic">Please select a user to continue.</div>}
                    </div>
                </div>
            </aside>

            {/* MAIN CONTENT */}
            <main className="flex-1 p-10 overflow-y-auto bg-white">
                <div className="max-w-[1400px]">
                    {/* HEADER */}
                    <header className="mb-8 flex justify-between items-start">
                        <div>
                            <h1 className="text-3xl font-bold flex items-center gap-3 mb-2 tracking-tight text-gray-900">
                                <span className="text-4xl">🎲</span>
                                {viewMode === "ADMIN_ONESHOT" ? "Oneshot Recruiter" :
                                    viewMode === "ADMIN_CROSS" ? "Cross-Group Overview" :
                                        `DnD Planner ${selectedGroup ? '- ' + selectedGroup : ''}`}
                            </h1>
                            <p className="text-gray-500">
                                {viewMode === "ADMIN_GHOST" ? `Simulating view for ${ghostUser}` : format(currentDate, "MMMM yyyy")}
                            </p>
                        </div>

                        {/* DATE CONTROLS */}
                        <div className="flex items-center gap-2">
                            <div className="flex items-center gap-2 bg-gray-100 border border-gray-200 rounded-md p-1">
                                <button className="p-2 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(subMonths(currentDate, 12))}>&laquo;</button>
                                <span className="font-mono text-sm px-2 text-gray-700">{format(currentDate, 'yyyy')}</span>
                                <button className="p-2 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(addMonths(currentDate, 12))}>&raquo;</button>
                            </div>
                            <div className="flex items-center gap-2 bg-gray-100 border border-gray-200 rounded-md p-1 min-w-[140px] justify-between px-2">
                                <span className="font-medium text-sm text-gray-800">{format(currentDate, "MMMM")}</span>
                                <div className="flex">
                                    <button className="p-1 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(subMonths(currentDate, 1))}><ChevronLeft size={16} /></button>
                                    <button className="p-1 hover:bg-gray-200 rounded text-gray-600" onClick={() => setCurrentDate(addMonths(currentDate, 1))}><ChevronRight size={16} /></button>
                                </div>
                            </div>
                        </div>
                    </header>

                    {/* VIEW CONTENT */}

                    {/* 1. ONESHOT RECRUITER VIEW */}
                    {viewMode === "ADMIN_ONESHOT" && (
                        <div className="space-y-6">
                            <div className="flex gap-4 p-4 bg-gray-50 border rounded-lg">
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Host Group (Playing)</span>
                                    <select className="w-full border p-2 rounded" value={crossGroup1 || ""} onChange={e => setCrossGroup1(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Guest Group (Recruiting)</span>
                                    <select className="w-full border p-2 rounded" value={crossGroup2 || ""} onChange={e => setCrossGroup2(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {getOneshotMatches().length === 0 ? (
                                    <div className="col-span-full text-center py-10 text-gray-400 bg-gray-50 rounded border border-dashed">
                                        No matches found for this month where {crossGroup1} is fully available.
                                    </div>
                                ) : getOneshotMatches().map((match, i) => (
                                    <div key={i} className="border border-green-200 bg-green-50 rounded-lg p-4">
                                        <div className="flex justify-between items-center mb-2">
                                            <span className="font-bold text-lg text-green-800">{format(match.date, "EEE, MMM do")}</span>
                                            <span className="bg-green-200 text-green-800 text-xs px-2 py-1 rounded-full">Match Found</span>
                                        </div>
                                        <div className="text-sm text-gray-600 mb-2">Host: <b className="text-gray-900">Full Team ✅</b></div>
                                        <div className="text-sm">
                                            Available Guests:
                                            <div className="flex flex-wrap gap-1 mt-1">
                                                {match.guests.map(g => (
                                                    <span key={g} className="bg-white border px-2 py-0.5 rounded text-xs">{g}</span>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* 2. ADMIN CROSS-GROUP VIEW */}
                    {viewMode === "ADMIN_CROSS" && (
                        <div className="space-y-6">
                            <div className="flex gap-4 p-4 bg-gray-50 border rounded-lg">
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Group 1</span>
                                    <select className="w-full border p-2 rounded" value={crossGroup1 || ""} onChange={e => setCrossGroup1(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Group 2</span>
                                    <select className="w-full border p-2 rounded" value={crossGroup2 || ""} onChange={e => setCrossGroup2(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                            </div>

                            <CalendarGrid
                                currentDate={currentDate}
                                availability={allAvailability} // Pass all, filter in render
                                maxPlayers={10} // Dummy
                                onDateClick={openDateDetails}
                                renderCell={(date: Date, _: any) => {
                                    const dStr = format(date, "yyyy-MM-dd");
                                    const dayData = allAvailability.filter(a => a.date === dStr);

                                    const getCount = (gName: string | null) => {
                                        if (!gName) return { ok: 0, total: 0 };
                                        const gPlayers = groups.find(g => g.name === gName)?.players.length || 0;
                                        const ok = dayData.filter(a => a.group_name === gName && a.status === 'Available').length;
                                        return { ok, total: gPlayers };
                                    };

                                    const g1Stats = getCount(crossGroup1);
                                    const g2Stats = getCount(crossGroup2);

                                    const Badge = ({ count, total, label }: any) => {
                                        const color = count === total ? "bg-green-100 text-green-700" : count > 0 ? "bg-yellow-50 text-yellow-700" : "bg-gray-50 text-gray-400";
                                        return (
                                            <div className={`text-[10px] px-1 py-0.5 rounded flex justify-between ${color}`}>
                                                <span>{label}</span>
                                                <b>{count}/{total}</b>
                                            </div>
                                        )
                                    };

                                    return (
                                        <div className="w-full h-full flex flex-col gap-1 p-0.5">
                                            {crossGroup1 && <Badge label={crossGroup1.substring(0, 4)} count={g1Stats.ok} total={g1Stats.total} />}
                                            {crossGroup2 && <Badge label={crossGroup2.substring(0, 4)} count={g2Stats.ok} total={g2Stats.total} />}
                                        </div>
                                    )
                                }}
                            />
                        </div>
                    )}


                    {/* 3. DEFAULT / GHOST / PERSONAL VIEW */}
                    {(viewMode === "PLAYER" || viewMode === "ADMIN_PERSONAL" || viewMode === "ADMIN_GHOST") && currentUser && (
                        <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
                            {/* LEFT: Personal Availability (or Ghost) */}
                            <section className={clsx("transition-all duration-300",
                                (viewMode === "PLAYER" && !ghostUser && currentUser === "Admin") ? "opacity-40 pointer-events-none" : "")}>

                                <div className="border border-gray-200 rounded-lg shadow-sm bg-white overflow-hidden">
                                    <div className="p-6 border-b border-gray-100 bg-gray-50/50">
                                        <h3 className="text-lg font-semibold flex items-center gap-2 text-gray-900">
                                            🗓️ {viewMode === "ADMIN_GHOST" ? `${ghostUser}'s` : currentUser === "Admin" && viewMode === "PLAYER" ? "Select Simulated User" : "Your"} Availability
                                        </h3>
                                        <p className="text-sm text-gray-500 mt-1">
                                            {viewMode === "PLAYER" && currentUser === "Admin" ? "Use the sidebar to select a user to ghost." : "Click dates to toggle your status."}
                                        </p>
                                    </div>
                                    <div className="p-6">
                                        <CalendarGrid
                                            currentDate={currentDate}
                                            availability={availability.filter(a => a.user_name === (viewMode === "PLAYER" && currentUser === "Admin" ? ghostUser : currentUser))}
                                            maxPlayers={1} // Self
                                            onDateClick={handleToggleStatus}
                                            onDateContextMenu={handleContextMenu}
                                            renderCell={(date: Date, stats: Availability[]) => {
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
                                    </div>
                                </div>
                            </section>

                            {/* RIGHT: Team Overview */}
                            <section>
                                <div className="border border-gray-200 rounded-lg shadow-sm bg-white overflow-hidden">
                                    <div className="p-6 border-b border-gray-100 bg-gray-50/50">
                                        <h3 className="text-lg font-semibold flex items-center gap-2 text-gray-900">⚔️ Team Overview</h3>
                                        <p className="text-sm text-gray-500 mt-1">Combined availability for {selectedGroup}</p>
                                    </div>
                                    <div className="p-6">
                                        <CalendarGrid
                                            currentDate={currentDate}
                                            availability={availability}
                                            maxPlayers={maxPlayers}
                                            onDateClick={openDateDetails}
                                        />
                                    </div>
                                </div>
                            </section>
                        </div>
                    )}
                </div>

                {/* CONTEXT MENU */}
                {contextMenu.isOpen && (
                    <>
                        {/* Overlay to close */}
                        <div
                            className="fixed inset-0 z-40"
                            onClick={() => setContextMenu({ ...contextMenu, isOpen: false })}
                        />

                        {/* Menu */}
                        <div
                            className="fixed z-50 bg-white rounded-lg shadow-xl border border-gray-200 py-1 w-48 animate-in fade-in zoom-in-95 duration-100"
                            style={{ top: contextMenu.y, left: contextMenu.x }}
                        >
                            <div className="px-3 py-2 border-b border-gray-100 text-xs font-bold text-gray-400 uppercase tracking-wider bg-gray-50/50">
                                Set Status for {contextMenu.date ? format(contextMenu.date, 'MMM do') : ''}
                            </div>
                            <button
                                className="w-full text-left px-4 py-2 hover:bg-green-50 text-green-700 text-sm flex items-center gap-2"
                                onClick={() => handleQuickStatus("Available")}
                            >
                                <span>✅</span> Available
                            </button>
                            <button
                                className="w-full text-left px-4 py-2 hover:bg-yellow-50 text-yellow-700 text-sm flex items-center gap-2"
                                onClick={() => handleQuickStatus("Maybe")}
                            >
                                <span>❓</span> Maybe
                            </button>
                            <button
                                className="w-full text-left px-4 py-2 hover:bg-red-50 text-red-700 text-sm flex items-center gap-2"
                                onClick={() => handleQuickStatus("No")}
                            >
                                <span>✕</span> No
                            </button>
                            <hr className="my-1 border-gray-100" />
                            <button
                                className="w-full text-left px-4 py-2 hover:bg-gray-50 text-gray-500 text-sm flex items-center gap-2"
                                onClick={() => handleQuickStatus(null)}
                            >
                                <span>🧹</span> Clear Selection
                            </button>
                        </div>
                    </>
                )}

                {/* DAY DETAILS MODAL */}
                {dateDetails.isOpen && dateDetails.date && (
                    <>
                        <div
                            className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm"
                            onClick={() => setDateDetails({ ...dateDetails, isOpen: false })}
                        />
                        <div className="fixed z-[70] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg shadow-2xl p-6 w-[90%] max-w-lg border border-gray-100 animate-in fade-in zoom-in-95 duration-200">
                            <div className="flex justify-between items-center mb-6">
                                <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                                    <span>📅</span> {format(dateDetails.date, 'EEEE, MMMM do')}
                                </h2>
                                <button
                                    onClick={() => setDateDetails({ ...dateDetails, isOpen: false })}
                                    className="p-1 hover:bg-gray-100 rounded-full text-gray-400 hover:text-gray-600 transition-colors"
                                >
                                    <X size={20} />
                                </button>
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                {(() => {
                                    const dStr = format(dateDetails.date, "yyyy-MM-dd");

                                    // Determine source data based on View Mode
                                    let activeAvailability = availability;
                                    let activePlayers = currentGroupPlayers;

                                    if (viewMode === "ADMIN_CROSS") {
                                        activeAvailability = allAvailability;
                                        const p1 = groups.find(g => g.name === crossGroup1)?.players || [];
                                        const p2 = groups.find(g => g.name === crossGroup2)?.players || [];
                                        activePlayers = [...p1, ...p2]; // Combine both groups
                                    }

                                    const dayStats = activeAvailability.filter(a => a.date === dStr);

                                    const available = dayStats.filter(a => a.status === 'Available' && activePlayers.includes(a.user_name)).map(a => a.user_name);
                                    const maybe = dayStats.filter(a => a.status === 'Maybe' && activePlayers.includes(a.user_name)).map(a => a.user_name);
                                    const no = dayStats.filter(a => a.status === 'No' && activePlayers.includes(a.user_name)).map(a => a.user_name);

                                    // Pending: Players in the active list who have NO status for this day
                                    const pending = activePlayers.filter(p => !dayStats.find(a => a.user_name === p && a.status));

                                    const ListBlock = ({ title, icon, color, list }: any) => (
                                        <div className={`border rounded-lg p-3 ${color} bg-opacity-50`}>
                                            <h4 className="font-bold text-sm mb-2 flex items-center gap-1.5 opacity-90">
                                                <span>{icon}</span> {title} <span className="opacity-60 ml-auto text-xs">({list.length})</span>
                                            </h4>
                                            {list.length > 0 ? (
                                                <div className="flex flex-wrap gap-1.5">
                                                    {list.map((p: string) => (
                                                        <span key={p} className="bg-white/80 px-2 py-0.5 rounded text-xs font-medium shadow-sm border border-black/5">
                                                            {p}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : <span className="text-xs opacity-50 italic">None</span>}
                                        </div>
                                    );

                                    return (
                                        <>
                                            <ListBlock title="Available" icon="✅" color="bg-green-50 text-green-800 border-green-200" list={available} />
                                            <ListBlock title="Maybe" icon="❓" color="bg-yellow-50 text-yellow-800 border-yellow-200" list={maybe} />
                                            <ListBlock title="No" icon="✕" color="bg-red-50 text-red-800 border-red-200" list={no} />
                                            <ListBlock title="Pending" icon="⏳" color="bg-gray-50 text-gray-600 border-gray-200" list={pending} />
                                        </>
                                    );
                                })()}
                            </div>
                        </div>
                    </>
                )}
            </main >
        </div >
    )
}
