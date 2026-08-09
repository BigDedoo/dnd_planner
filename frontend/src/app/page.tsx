"use client";

import { useEffect, useState } from "react";
import { format, addMonths, subMonths, startOfMonth, endOfMonth, eachDayOfInterval } from "date-fns";
import { fetchGroups, fetchAvailability, updateAvailability, fetchAllAvailability, Group, Availability } from "@/services/api";
import { CalendarGrid } from "@/components/CalendarGrid";
import { AlertTriangle, CalendarDays, ChevronLeft, ChevronRight, Dices, Layers3, Music, Shield, User, Users, X, type LucideIcon } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import clsx from "clsx";

type ViewMode = "PLAYER" | "OVERVIEW_GROUP" | "OVERVIEW_CROSS" | "OVERVIEW_ONESHOT";

const getInitials = (name: string) => {
    return name.slice(0, 2).toUpperCase();
};

const getAvatarColor = (name: string) => {
    const colors = [
        "bg-red-500 text-white",
        "bg-blue-500 text-white",
        "bg-green-500 text-white",
        "bg-yellow-500 text-black",
        "bg-purple-500 text-white",
        "bg-pink-500 text-white",
        "bg-indigo-500 text-white",
        "bg-teal-500 text-white",
        "bg-orange-500 text-white",
    ];
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const index = Math.abs(hash) % colors.length;
    return colors[index];
};

const renderAvatarContent = (name: string, size: number) => {
    if (name === "Daerrus") {
        return <Shield size={size} className="text-white" />;
    }
    if (name === "Quentin") {
        return <Music size={size} className="text-white" />;
    }
    return getInitials(name);
};

interface GroupBadgeProps {
    count: number;
    total: number;
    label: string;
}

interface DayStatusListProps {
    title: string;
    icon: string;
    color: string;
    list: string[];
}

interface GroupConflictInfo {
    groupName: string;
    players: string[];
}

interface NavItem {
    icon: LucideIcon;
    label: string;
    mode: ViewMode;
    section: "main" | "tools";
}

export default function Home() {
    // -- Data State --
    const [groups, setGroups] = useState<Group[]>([]);
    const [allAvailability, setAllAvailability] = useState<Availability[]>([]); // For overview views

    // -- Selection State --
    const [currentUser, setCurrentUser] = useState<string | null>(null);
    const [viewMode, setViewMode] = useState<ViewMode>("PLAYER");
    const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);

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
    const [selectedScheduleDate, setSelectedScheduleDate] = useState(new Date());
    const [availability, setAvailability] = useState<Availability[]>([]);
    const [syncSuccessMessage, setSyncSuccessMessage] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState("");

    const userGroups = currentUser
        ? groups.filter((group) => group.players.includes(currentUser))
        : [];
    const userGroup = userGroups[0] ?? null;

    const activeViewMode: ViewMode = viewMode;
    const activeSelectedGroup = activeViewMode === "PLAYER"
        ? userGroup?.name ?? null
        : (selectedGroup && groups.some((group) => group.name === selectedGroup) ? selectedGroup : groups[0]?.name ?? null);

    const allPlayers = Array.from(new Set(groups.flatMap(g => g.players))).sort();

    const filteredPlayers = allPlayers.filter(player => {
        const query = searchQuery.toLowerCase();
        const matchesPlayerName = player.toLowerCase().includes(query);
        const playerGroups = groups.filter(g => g.players.includes(player)).map(g => g.name.toLowerCase());
        const matchesGroupName = playerGroups.some(gName => gName.includes(query));
        return matchesPlayerName || matchesGroupName;
    });

    const selectPlayer = (player: string | null) => {
        setCurrentUser(player);
        if (player) {
            localStorage.setItem("activePlayer", player);
        } else {
            localStorage.removeItem("activePlayer");
        }
    };

    // -- Load Groups & Restore Persisted User --
    useEffect(() => {
        fetchGroups().then(data => {
            setGroups(data);
            if (data.length > 0) {
                // Default selection logic if needed
                setCrossGroup1(data[0].name);
                if (data.length > 1) setCrossGroup2(data[1].name);

                // Restore active player from localStorage
                const persistedPlayer = localStorage.getItem("activePlayer");
                if (persistedPlayer) {
                    const playerExists = data.some(g => g.players.includes(persistedPlayer));
                    if (playerExists) {
                        setCurrentUser(persistedPlayer);
                    } else {
                        localStorage.removeItem("activePlayer");
                        setCurrentUser(null);
                    }
                }
            }
        });
    }, []);

    // -- Load Availability --
    useEffect(() => {
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth() + 1;

        if (activeViewMode === "OVERVIEW_CROSS" || activeViewMode === "OVERVIEW_ONESHOT") {
            // Load ALL data for the month
            const start = format(startOfMonth(currentDate), "yyyy-MM-dd");
            const end = format(endOfMonth(currentDate), "yyyy-MM-dd");
            fetchAllAvailability(start, end).then(setAllAvailability);
        } else if (activeViewMode === "PLAYER" && currentUser) {
            const start = format(startOfMonth(currentDate), "yyyy-MM-dd");
            const end = format(endOfMonth(currentDate), "yyyy-MM-dd");
            const currentUserGroups = groups.filter((group) => group.players.includes(currentUser));
            const promises = currentUserGroups.map(g => fetchAvailability(g.name, year, month));
            Promise.all([
                Promise.all(promises).then((results) => setAvailability(results.flat())),
                fetchAllAvailability(start, end).then(setAllAvailability),
            ]);
        } else if (activeViewMode === "OVERVIEW_GROUP" && activeSelectedGroup) {
            const start = format(startOfMonth(currentDate), "yyyy-MM-dd");
            const end = format(endOfMonth(currentDate), "yyyy-MM-dd");
            const promises = [fetchAvailability(activeSelectedGroup, year, month)];
            Promise.all([
                Promise.all(promises).then((results) => setAvailability(results.flat())),
                fetchAllAvailability(start, end).then(setAllAvailability),
            ]);
        } else if (activeSelectedGroup) {
            const promises = [fetchAvailability(activeSelectedGroup, year, month)];
            Promise.all(promises).then((results) => {
                setAvailability(results.flat());
            });
        }
    }, [activeSelectedGroup, currentDate, activeViewMode, currentUser, groups]);


    // -- Handlers --
    const handleToggleStatus = async (date: Date) => {
        const targetUser = currentUser;
        const targetGroup = activeSelectedGroup;

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

        // Find all groups the user is in to perform optimistic updates for all of them
        const playerGroups = getPlayerGroupNames(targetUser);
        const newEntries = playerGroups.map(gName => ({
            group_name: gName,
            user_name: targetUser,
            date: dateStr,
            status: nextStatus || ""
        }));

        // Optimistic update
        const others = currentData.filter(a => !(a.date === dateStr && a.user_name === targetUser));
        const nextList = nextStatus ? [...others, ...newEntries] : others;
        setAvailability(nextList);

        const othersAll = allAvailability.filter(a => !(a.date === dateStr && a.user_name === targetUser));
        const nextAllList = nextStatus ? [...othersAll, ...newEntries] : othersAll;
        setAllAvailability(nextAllList);

        await updatePlayerAvailabilityAcrossGroups(targetUser, dateStr, nextStatus);
    };

    const handleScheduleDateClick = async (date: Date) => {
        setSelectedScheduleDate(date);
        await handleToggleStatus(date);
    };

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

        const targetUser = currentUser;
        const targetGroup = activeSelectedGroup;

        if (!targetGroup || !targetUser) {
            alert("Please select a user first!");
            setContextMenu({ ...contextMenu, isOpen: false });
            return;
        }

        const dateStr = format(contextMenu.date, "yyyy-MM-dd");

        // Find all groups the user is in to perform optimistic updates for all of them
        const playerGroups = getPlayerGroupNames(targetUser);
        const newEntries = playerGroups.map(gName => ({
            group_name: gName,
            user_name: targetUser,
            date: dateStr,
            status: status || ""
        }));

        // Optimistic update
        const others = availability.filter(a => !(a.date === dateStr && a.user_name === targetUser));
        const nextList = status ? [...others, ...newEntries] : others;
        setAvailability(nextList);

        const othersAll = allAvailability.filter(a => !(a.date === dateStr && a.user_name === targetUser));
        const nextAllList = status ? [...othersAll, ...newEntries] : othersAll;
        setAllAvailability(nextAllList);

        setContextMenu({ ...contextMenu, isOpen: false });

        await updatePlayerAvailabilityAcrossGroups(targetUser, dateStr, status);
    };

    const handleSyncAvailability = async () => {
        const targetUser = currentUser === "Rico" ? "Gaelle" : "Rico";
        if (!activeSelectedGroup || !currentUser) {
            return;
        }

        // Get my availabilities
        const myAvails = availability.filter(a => a.user_name === currentUser);
        
        const updatesToMake: {date: string, status: string | null}[] = [];
        
        myAvails.forEach(myAvail => {
            const targetAvail = availability.find(a => a.user_name === targetUser && a.date === myAvail.date);
            if (!targetAvail || targetAvail.status !== myAvail.status) {
                updatesToMake.push({ date: myAvail.date, status: myAvail.status });
            }
        });

        if (updatesToMake.length === 0) {
            setSyncSuccessMessage(`${targetUser} is already fully synced!`);
            setTimeout(() => setSyncSuccessMessage(null), 3000);
            return;
        }

        // Optimistic update
        let nextList = [...availability];
        const targetUserGroups = getPlayerGroupNames(targetUser);
        updatesToMake.forEach(update => {
            nextList = nextList.filter(a => !(a.user_name === targetUser && a.date === update.date));
            if (update.status) {
                const status = update.status;
                targetUserGroups.forEach((groupName) => {
                    nextList.push({ group_name: groupName, user_name: targetUser, date: update.date, status });
                });
            }
        });
        setAvailability(nextList);

        // Execute API calls
        try {
            await Promise.all(
                updatesToMake.flatMap((update) =>
                    targetUserGroups.map((groupName) =>
                        updateAvailability(groupName, targetUser, update.date, update.status)
                    )
                )
            );
            setSyncSuccessMessage(`Successfully synced ${updatesToMake.length} days to ${targetUser}!`);
            setTimeout(() => setSyncSuccessMessage(null), 3000);
        } catch (e) {
            console.error("Failed to sync availability", e);
            alert("Failed to sync availability. Please refresh and try again.");
        }
    };

    const openDateDetails = (date: Date) => {
        setDateDetails({ isOpen: true, date });
    };

    // -- Derived Data --
    const rawGroupPlayers = groups.find(g => g.name === activeSelectedGroup)?.players || [];
    const currentGroupPlayers = rawGroupPlayers;
    const crossGroup1Players = groups.find(g => g.name === crossGroup1)?.players || [];
    const crossGroup2Players = groups.find(g => g.name === crossGroup2)?.players || [];
    const sharedCrossGroupPlayers = crossGroup1 && crossGroup2
        ? crossGroup1Players.filter((player) => crossGroup2Players.includes(player))
        : [];

    const maxPlayers = currentGroupPlayers.length;
    const selectedDateStr = format(selectedScheduleDate, "yyyy-MM-dd");
    const selectedDateStats = availability.filter((entry) => entry.date === selectedDateStr);

    const selectedPlayerStatus = selectedDateStats.find((entry) => entry.user_name === currentUser)?.status;

    const getPlayerGroupNames = (player: string) => {
        return groups.filter((group) => group.players.includes(player)).map((group) => group.name);
    };

    const updatePlayerAvailabilityAcrossGroups = async (player: string, dateStr: string, status: string | null) => {
        const playerGroups = getPlayerGroupNames(player);
        await Promise.all(
            playerGroups.map((groupName) => updateAvailability(groupName, player, dateStr, status))
        );
    };

    const getAvailablePlayersForDate = (groupName: string, dateStr: string) => {
        const groupPlayers = groups.find((group) => group.name === groupName)?.players ?? [];
        const dayEntries = availability.filter(
            (entry) => entry.date === dateStr && entry.group_name === groupName
        );

        return Array.from(
            new Set(
                dayEntries
                    .filter((entry) => entry.status === "Available" && groupPlayers.includes(entry.user_name))
                    .map((entry) => entry.user_name)
            )
        );
    };

    const formatPlayerList = (players: string[]) => {
        if (players.length === 1) return players[0];
        if (players.length === 2) return `${players[0]} and ${players[1]}`;
        return `${players.slice(0, -1).join(", ")}, and ${players[players.length - 1]}`;
    };

    const getRunSummary = (groupName: string, dateStr: string) => {
        const groupPlayers = groups.find((group) => group.name === groupName)?.players ?? [];
        const availablePlayers = getAvailablePlayersForDate(groupName, dateStr);
        const missingPlayers = groupPlayers.filter((player) => !availablePlayers.includes(player));

        if (groupPlayers.length === 0) {
            return {
                title: `${groupName} has no players`,
                detail: "",
                isReady: false,
            };
        }

        if (missingPlayers.length === 0) {
            return {
                title: `${groupName} can run`,
                detail: "",
                isReady: true,
            };
        }

        return {
            title: `${groupName} could run`,
            detail: `if ${formatPlayerList(missingPlayers)} were available`,
            isReady: false,
        };
    };

    const getConflictsForGroup = (groupName: string, dateStr: string): GroupConflictInfo[] => {
        const targetGroupObj = groups.find(g => g.name === groupName);
        if (!targetGroupObj) return [];
        const groupPlayerCount = targetGroupObj.players.length;

        const dayData = allAvailability.filter((entry) => entry.date === dateStr);
        const selectedGroupAvailable = dayData.filter(
            (entry) => entry.group_name === groupName && entry.status === "Available"
        ).length;

        if (selectedGroupAvailable !== groupPlayerCount) {
            return [];
        }

        return groups.flatMap((group) => {
            if (group.name === groupName) return [];

            const sharedPlayers = targetGroupObj.players.filter((player) => group.players.includes(player));
            if (sharedPlayers.length === 0) return [];

            const groupAvailable = dayData.filter(
                (entry) => entry.group_name === group.name && entry.status === "Available"
            ).length;

            return groupAvailable === group.players.length
                ? [{ groupName: group.name, players: sharedPlayers }]
                : [];
        });
    };

    const getOverviewConflicts = (dateStr: string): GroupConflictInfo[] => {
        if (!activeSelectedGroup) return [];
        return getConflictsForGroup(activeSelectedGroup, dateStr);
    };

    const getConflictDescriptions = (conflicts: GroupConflictInfo[]) => {
        return conflicts.map((conflict) => {
            const playersLabel = conflict.players.join(", ");
            const verb = conflict.players.length === 1 ? "is" : "are";
            return `${playersLabel} ${verb} also in ${conflict.groupName}, which can also run that day.`;
        });
    };

    const createOverviewCellRenderer = (groupName: string, totalPlayers: number) => {
        function renderOverviewCell(date: Date, stats: Availability[]) {
            const dateStr = format(date, "yyyy-MM-dd");
            const available = stats.filter((entry) => entry.group_name === groupName && entry.status === "Available").length;
            const conflicts = getConflictsForGroup(groupName, dateStr);
            const indicatorClass = getAvailabilityBadgeClass(available, totalPlayers);
            const conflictTitle = getConflictDescriptions(conflicts).join("\n");

            return (
                <div className="w-full h-full flex flex-col gap-1 p-0.5">
                    {conflicts.length > 0 && (
                        <div
                            className="self-end text-amber-600 dark:text-amber-400"
                            title={`Scheduling conflict:\n${conflictTitle}`}
                        >
                            <AlertTriangle size={12} />
                        </div>
                    )}
                    <div className="w-full h-full flex items-center justify-center mt-1">
                        {available > 0 ? (
                            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${indicatorClass}`}>
                                {available}/{totalPlayers}
                            </span>
                        ) : (
                            <span className="text-xs text-gray-300 dark:text-slate-600">-</span>
                        )}
                    </div>
                </div>
            );
        }

        return renderOverviewCell;
    };

    const daysInCurrentMonth = eachDayOfInterval({
        start: startOfMonth(currentDate),
        end: endOfMonth(currentDate),
    });

    const bestDateGroups = activeViewMode === "PLAYER"
        ? userGroups
        : groups.filter((group) => group.name === activeSelectedGroup);

    const bestDates = bestDateGroups.length > 0
        ? daysInCurrentMonth
            .flatMap((date) => {
                const dateStr = format(date, "yyyy-MM-dd");

                return bestDateGroups.map((group) => {
                    const availablePlayers = getAvailablePlayersForDate(group.name, dateStr);
                    const available = availablePlayers.length;

                    return {
                        date,
                        dateStr,
                        groupName: group.name,
                        available,
                        totalPlayers: group.players.length,
                        conflicts: getConflictsForGroup(group.name, dateStr),
                        summary: getRunSummary(group.name, dateStr),
                    };
                });
            })
            .filter((day) => day.available > 0)
            .sort((a, b) => {
                const readyScore = Number(b.available >= b.totalPlayers) - Number(a.available >= a.totalPlayers);
                return readyScore || b.available - a.available || a.date.getTime() - b.date.getTime() || a.groupName.localeCompare(b.groupName);
            })
        : [];


    const getStatusLabel = (status?: string) => {
        if (status === "Available") return "Available";
        if (status === "Maybe") return "Maybe";
        if (status === "No") return "Unavailable";
        return "Not set";
    };

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
    };

    const navItems: NavItem[] = [
        { icon: User, label: "My Schedule", mode: "PLAYER", section: "main" },
        { icon: Users, label: "Group Schedule", mode: "OVERVIEW_GROUP", section: "main" },
        { icon: Layers3, label: "All Groups", mode: "OVERVIEW_CROSS", section: "main" },
        { icon: Dices, label: "Recruit Players", mode: "OVERVIEW_ONESHOT", section: "tools" },
    ];

    const renderNavItem = ({ icon: Icon, label, mode }: NavItem) => {
        const isActive = activeViewMode === mode;

        return (
            <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                aria-current={isActive ? "page" : undefined}
                aria-label={label}
                title={isSidebarOpen ? undefined : label}
                className={clsx(
                    "relative flex min-h-11 w-full items-center rounded-lg border text-sm transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-50 dark:focus-visible:ring-offset-slate-950",
                    isSidebarOpen ? "justify-start gap-3 px-3 py-2.5" : "justify-center px-0 py-2.5",
                    isActive
                        ? "border-blue-200 bg-blue-50 text-blue-700 shadow-sm dark:border-blue-900/70 dark:bg-blue-950/40 dark:text-blue-100"
                        : "border-transparent text-gray-700 hover:bg-gray-100 hover:text-gray-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                )}
            >
                {isActive && <span className="absolute inset-y-2 left-0 w-1 rounded-r-full bg-blue-500" aria-hidden="true" />}
                <Icon size={18} className="shrink-0" />
                {isSidebarOpen && <span className={clsx("truncate", isActive && "font-semibold")}>{label}</span>}
            </button>
        );
    };

    const getAvailabilityBadgeClass = (available: number, total: number) => {
        if (available === total) return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400";
        if (available >= total / 2) return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400";
        if (available > 0) return "bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-300";
        return "";
    };


    if (groups.length === 0) {
        return (
            <div className="flex min-h-screen bg-gray-50 dark:bg-slate-950 items-center justify-center">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500"></div>
            </div>
        );
    }

    if (!currentUser) {
        return (
            <div className="flex min-h-screen bg-gray-50 dark:bg-slate-950 text-gray-900 dark:text-slate-100 font-sans transition-colors items-center justify-center p-6 sm:p-12 animate-in fade-in duration-300">
                <div className="max-w-4xl w-full space-y-8">
                    <div className="text-center space-y-3">
                        <div className="inline-flex size-16 items-center justify-center rounded-2xl bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-100 dark:border-blue-900/50 shadow-md">
                            <span className="text-4xl">🎲</span>
                        </div>
                        <h1 className="text-3xl font-extrabold tracking-tight">Who are you?</h1>
                        <p className="text-gray-500 dark:text-slate-400 max-w-md mx-auto text-sm">
                            Select your profile to view and update your availability. Your availability applies globally across all of your groups.
                        </p>
                    </div>

                    {/* Search */}
                    <div className="max-w-md mx-auto relative">
                        <label htmlFor="player-search" className="sr-only">Search players or groups</label>
                        <input
                            id="player-search"
                            type="text"
                            placeholder="Search by player name or group..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full pl-4 pr-10 py-3 rounded-xl border border-gray-200 bg-white dark:bg-slate-900 dark:border-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all shadow-sm placeholder:text-gray-400 dark:placeholder:text-slate-500"
                        />
                        <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-gray-400 dark:text-slate-500">
                            {/* Search Icon */}
                            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                            </svg>
                        </div>
                    </div>

                    {/* Players Grid */}
                    {filteredPlayers.length > 0 ? (
                        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6 max-h-[50vh] overflow-y-auto p-2 scrollbar-thin">
                            {filteredPlayers.map((player) => {
                                const playerGroups = groups.filter(g => g.players.includes(player));
                                return (
                                    <button
                                        key={player}
                                        onClick={() => selectPlayer(player)}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter" || e.key === " ") {
                                                e.preventDefault();
                                                selectPlayer(player);
                                            }
                                        }}
                                        className="flex items-center gap-4 p-4 rounded-xl border border-gray-200 bg-white hover:border-blue-500 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-blue-500 transition-all text-left shadow-sm hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer group"
                                    >
                                        <div className={clsx("flex size-12 shrink-0 items-center justify-center rounded-full text-base font-bold shadow-sm transition-transform group-hover:scale-105", getAvatarColor(player))}>
                                            {renderAvatarContent(player, 20)}
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <div className="font-bold text-gray-900 dark:text-slate-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors truncate">
                                                {player}
                                            </div>
                                            <div className="flex flex-wrap gap-1 mt-1.5">
                                                {playerGroups.map(g => (
                                                    <span key={g.name} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gray-100 text-gray-700 dark:bg-slate-800 dark:text-slate-300 border dark:border-slate-700">
                                                        {g.name}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    ) : (
                        <div className="text-center py-12 text-gray-400 dark:text-slate-500">
                            No profiles match &quot;{searchQuery}&quot;
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 font-sans transition-colors">

            {/* SIDEBAR */}
            <aside
                className={clsx(
                    "relative flex shrink-0 flex-col border-r border-gray-200 bg-gray-50 transition-all duration-300 dark:border-slate-800 dark:bg-slate-950",
                    isSidebarOpen ? "w-[300px] px-6 pb-6 pt-10" : "w-[88px] px-3 pb-6 pt-10"
                )}
            >
                <button
                    type="button"
                    onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                    className={clsx(
                        "absolute top-6 z-50 cursor-pointer rounded-full border border-gray-200 bg-white p-2 shadow-md transition-all duration-300 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700",
                        isSidebarOpen ? "-right-3" : "-right-12 border-l-4 border-l-blue-500"
                    )}
                    aria-label={isSidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
                    title={isSidebarOpen ? "Collapse Sidebar" : "Expand Sidebar"}
                >
                    {isSidebarOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
                </button>

                <div className="flex h-full flex-col">
                    <div className={clsx("mb-6", isSidebarOpen ? "mt-0" : "mt-1")}>
                        <div
                            className={clsx(
                                "flex items-center text-gray-800 dark:text-slate-200",
                                isSidebarOpen ? "gap-3" : "justify-center"
                            )}
                        >
                            <div className="flex size-10 items-center justify-center rounded-xl border border-blue-100 bg-blue-50 text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/40 dark:text-blue-200">
                                <CalendarDays size={18} />
                            </div>
                            {isSidebarOpen && (
                                <div>
                                    <h2 className="text-lg font-semibold">Scheduling</h2>
                                    <p className="text-xs text-gray-500 dark:text-slate-400">Plan sessions across groups</p>
                                </div>
                            )}
                        </div>
                    </div>

                    {currentUser && (
                        <section className="mb-6">
                            {isSidebarOpen ? (
                                <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900 flex items-start gap-3 relative animate-in fade-in duration-200">
                                    <div className={clsx("flex size-10 shrink-0 items-center justify-center rounded-xl text-base font-bold shadow-sm", getAvatarColor(currentUser))}>
                                        {renderAvatarContent(currentUser, 18)}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-extrabold text-gray-900 dark:text-slate-100 truncate">{currentUser}</div>
                                        <div className="text-[10px] font-medium text-gray-500 dark:text-slate-400 truncate mt-0.5" title={userGroups.map(g => g.name).join(", ")}>
                                            {userGroups.map(g => g.name).join(", ")}
                                        </div>
                                        <button
                                            onClick={() => selectPlayer(null)}
                                            className="mt-2 inline-flex items-center text-xs font-semibold text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 rounded cursor-pointer"
                                            aria-label="Switch active player profile"
                                        >
                                            Switch profile
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <div className="flex justify-center">
                                    <button
                                        onClick={() => selectPlayer(null)}
                                        className={clsx("flex size-10 items-center justify-center rounded-xl text-base font-bold shadow-sm hover:scale-105 transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer", getAvatarColor(currentUser))}
                                        aria-label={`Switch active profile (currently logged in as ${currentUser})`}
                                        title={`Switch profile (Viewing as ${currentUser})`}
                                    >
                                        {renderAvatarContent(currentUser, 18)}
                                    </button>
                                </div>
                            )}
                        </section>
                    )}

                    <nav className="flex flex-1 flex-col" aria-label="Sidebar navigation">
                        <section className="space-y-2">
                            {isSidebarOpen && (
                                <h3 className="px-1 text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-slate-400">
                                    Main
                                </h3>
                            )}
                            <div className="space-y-1.5">
                                {navItems.filter((item) => item.section === "main").map(renderNavItem)}
                            </div>
                        </section>

                        <section className="mt-6 space-y-2">
                            {isSidebarOpen && (
                                <h3 className="px-1 text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-slate-400">
                                    Tools
                                </h3>
                            )}
                            <div className="space-y-1.5">
                                {navItems.filter((item) => item.section === "tools").map(renderNavItem)}
                            </div>
                        </section>
                    </nav>


                </div>
            </aside>

            {/* MAIN CONTENT */}
            <main className="flex-1 p-10 overflow-y-auto bg-white dark:bg-slate-900">
                <div className="max-w-[1400px]">
                    {/* HEADER */}
                    <header className="mb-8 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                        <div>
                            <h1 className="text-2xl font-bold flex items-center gap-3 mb-2 tracking-tight text-gray-900 dark:text-slate-100">
                                <span className="text-4xl">🎲</span>
                                {activeViewMode === "OVERVIEW_ONESHOT" ? "Oneshot Recruiter" :
                                    activeViewMode === "OVERVIEW_CROSS" ? "All Groups" :
                                        activeViewMode === "OVERVIEW_GROUP" ? "Group Schedule" :
                                        "My Schedule"}
                            </h1>
                            {activeSelectedGroup && activeViewMode === "OVERVIEW_GROUP" && (
                                <span className="inline-flex items-center rounded-md border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/40 dark:text-blue-200">
                                    {activeSelectedGroup}
                                </span>
                            )}
                        </div>

                        <div className="flex flex-wrap items-center gap-3">
                            <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 shadow-sm dark:border-slate-700 dark:bg-slate-800">
                                <button
                                    className="rounded-md px-2 py-2 text-gray-600 transition-colors hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:text-slate-300 dark:hover:bg-slate-700"
                                    onClick={() => setCurrentDate(subMonths(currentDate, 12))}
                                    aria-label="Previous year"
                                >
                                    &laquo;
                                </button>
                                <button
                                    className="rounded-md p-2 text-gray-600 transition-colors hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:text-slate-300 dark:hover:bg-slate-700"
                                    onClick={() => setCurrentDate(subMonths(currentDate, 1))}
                                    aria-label="Previous month"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <span className="min-w-[150px] px-3 text-center text-sm font-semibold text-gray-800 dark:text-slate-100">
                                    {format(currentDate, "MMMM yyyy")}
                                </span>
                                <button
                                    className="rounded-md p-2 text-gray-600 transition-colors hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:text-slate-300 dark:hover:bg-slate-700"
                                    onClick={() => setCurrentDate(addMonths(currentDate, 1))}
                                    aria-label="Next month"
                                >
                                    <ChevronRight size={16} />
                                </button>
                                <button
                                    className="rounded-md px-2 py-2 text-gray-600 transition-colors hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:text-slate-300 dark:hover:bg-slate-700"
                                    onClick={() => setCurrentDate(addMonths(currentDate, 12))}
                                    aria-label="Next year"
                                >
                                    &raquo;
                                </button>
                                <button
                                    className="ml-1 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-700"
                                    onClick={() => {
                                        const today = new Date();
                                        setCurrentDate(today);
                                        setSelectedScheduleDate(today);
                                    }}
                                >
                                    Today
                                </button>
                            </div>
                            <div className="h-10 w-px bg-gray-200 dark:bg-slate-700" aria-hidden="true" />
                            <ThemeToggle />
                        </div>
                    </header>

                    {/* VIEW CONTENT */}

                    {/* 1. ONESHOT RECRUITER VIEW */}
                    {activeViewMode === "OVERVIEW_ONESHOT" && (
                        <div className="space-y-6">
                            <div className="flex gap-4 p-4 bg-gray-50 dark:bg-slate-800/50 border dark:border-slate-700 rounded-lg">
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Host Group (Playing)</span>
                                    <select className="w-full border dark:border-slate-700 p-2 rounded bg-white dark:bg-slate-800" value={crossGroup1 || ""} onChange={e => setCrossGroup1(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Guest Group (Recruiting)</span>
                                    <select className="w-full border dark:border-slate-700 p-2 rounded bg-white dark:bg-slate-800" value={crossGroup2 || ""} onChange={e => setCrossGroup2(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {getOneshotMatches().length === 0 ? (
                                    <div className="col-span-full text-center py-10 text-gray-400 dark:text-slate-500 bg-gray-50 dark:bg-slate-800/50 rounded border dark:border-slate-700 border-dashed">
                                        No matches found for this month where {crossGroup1} is fully available.
                                    </div>
                                ) : getOneshotMatches().map((match, i) => (
                                    <div key={i} className="border border-green-200 bg-green-50 rounded-lg p-4">
                                        <div className="flex justify-between items-center mb-2">
                                            <span className="font-bold text-lg text-green-800">{format(match.date, "EEE, MMM do")}</span>
                                            <span className="bg-green-200 text-green-800 text-xs px-2 py-1 rounded-full">Match Found</span>
                                        </div>
                                        <div className="text-sm text-gray-600 dark:text-slate-400 mb-2">Host: <b className="text-gray-900 dark:text-slate-200">Full Team ✅</b></div>
                                        <div className="text-sm">
                                            Available Guests:
                                            <div className="flex flex-wrap gap-1 mt-1">
                                                {match.guests.map(g => (
                                                    <span key={g} className="bg-white dark:bg-slate-800 border dark:border-slate-700 px-2 py-0.5 rounded text-xs">{g}</span>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* 2. CROSS-GROUP VIEW */}
                    {activeViewMode === "OVERVIEW_CROSS" && (
                        <div className="space-y-6">
                            <div className="flex gap-4 p-4 bg-gray-50 dark:bg-slate-800/50 border dark:border-slate-700 rounded-lg">
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Group 1</span>
                                    <select className="w-full border dark:border-slate-700 p-2 rounded bg-white dark:bg-slate-800" value={crossGroup1 || ""} onChange={e => setCrossGroup1(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                                <label className="flex-1">
                                    <span className="text-sm font-bold block mb-1">Group 2</span>
                                    <select className="w-full border dark:border-slate-700 p-2 rounded bg-white dark:bg-slate-800" value={crossGroup2 || ""} onChange={e => setCrossGroup2(e.target.value)}>
                                        {groups.map(g => <option key={g.name} value={g.name}>{g.name}</option>)}
                                    </select>
                                </label>
                            </div>

                            <CalendarGrid
                                currentDate={currentDate}
                                availability={allAvailability} // Pass all, filter in render
                                maxPlayers={10} // Dummy
                                onDateClick={openDateDetails}
                                renderCell={(date: Date) => {
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
                                    const hasCrossGroupConflict = sharedCrossGroupPlayers.length > 0
                                        && g1Stats.total > 0
                                        && g2Stats.total > 0
                                        && g1Stats.ok === g1Stats.total
                                        && g2Stats.ok === g2Stats.total;
                                    const sharedPlayersLabel = sharedCrossGroupPlayers.join(", ");

                                    const Badge = ({ count, total, label }: GroupBadgeProps) => {
                                        const color = count === total ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : count > 0 ? "bg-yellow-50 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" : "bg-gray-50 text-gray-400 dark:bg-slate-800 dark:text-slate-500";
                                        return (
                                            <div className={`text-[10px] px-1 py-0.5 rounded flex justify-between ${color}`}>
                                                <span>{label}</span>
                                                <b>{count}/{total}</b>
                                            </div>
                                        )
                                    };

                                    return (
                                        <div className="w-full h-full flex flex-col gap-1 p-0.5">
                                            {hasCrossGroupConflict && (
                                                <div
                                                    className="self-end text-amber-600 dark:text-amber-400"
                                                    title={`Scheduling conflict: ${sharedPlayersLabel} ${
                                                        sharedCrossGroupPlayers.length === 1 ? "is" : "are"
                                                    } in both groups, and both groups can run that day.`}
                                                >
                                                    <AlertTriangle size={12} />
                                                </div>
                                            )}
                                            {crossGroup1 && <Badge label={crossGroup1.substring(0, 4)} count={g1Stats.ok} total={g1Stats.total} />}
                                            {crossGroup2 && <Badge label={crossGroup2.substring(0, 4)} count={g2Stats.ok} total={g2Stats.total} />}
                                        </div>
                                    )
                                }}
                            />
                        </div>
                    )}


                    {/* 3. GROUP OVERVIEW */}
                    {activeViewMode === "OVERVIEW_GROUP" && (
                        <div className="space-y-6">
                            <div className="p-4 bg-gray-50 dark:bg-slate-800/50 border dark:border-slate-700 rounded-lg">
                                <label className="block">
                                    <span className="text-sm font-bold block mb-1">Overview Group</span>
                                    <select
                                        className="w-full md:max-w-sm border dark:border-slate-700 p-2 rounded bg-white dark:bg-slate-800"
                                        value={activeSelectedGroup || ""}
                                        onChange={(e) => setSelectedGroup(e.target.value || null)}
                                    >
                                        {groups.map((group) => (
                                            <option key={group.name} value={group.name}>
                                                {group.name}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            </div>

                            <section>
                                <div className="border border-gray-200 dark:border-slate-800 rounded-lg shadow-sm bg-white dark:bg-slate-900 overflow-hidden">
                                    <div className="p-6 border-b border-gray-100 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-800/50">
                                        <h3 className="text-lg font-semibold flex items-center gap-2 text-gray-900 dark:text-slate-100">⚔️ Group Availability</h3>
                                        <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
                                            Combined availability for {activeSelectedGroup}
                                        </p>
                                    </div>
                                    <div className="p-6">
                                        {activeSelectedGroup ? (
                                            <CalendarGrid
                                                currentDate={currentDate}
                                                availability={availability}
                                                maxPlayers={maxPlayers}
                                                onDateClick={openDateDetails}
                                                renderCell={createOverviewCellRenderer(activeSelectedGroup, maxPlayers)}
                                            />
                                        ) : (
                                            <div className="text-sm text-gray-500 dark:text-slate-400">
                                                No groups are available yet.
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </section>
                        </div>
                    )}

                    {/* 4. PLAYER VIEW */}
                    {activeViewMode === "PLAYER" && currentUser && (
                        <div className="space-y-6">


                            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.85fr)]">
                                <section className="transition-all duration-300 space-y-6">
                                    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
                                        <div className="border-b border-gray-100 bg-gray-50/50 p-6 dark:border-slate-800 dark:bg-slate-800/50">
                                            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                                                <div>
                                                    <h3 className="text-lg font-semibold text-gray-900 dark:text-slate-100">Set your availability</h3>
                                                    <p className="mt-1 text-sm text-gray-600 dark:text-slate-300">
                                                        Click dates to mark when {currentUser} is available, tentative, or unavailable.
                                                    </p>
                                                </div>
                                                {(currentUser === "Rico" || currentUser === "Gaelle") && (
                                                    <button
                                                        onClick={handleSyncAvailability}
                                                        className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 shadow-sm transition-colors hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50"
                                                    >
                                                        Sync to {currentUser === "Rico" ? "Gaelle" : "Rico"}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                        <div className="p-6">
                                            <CalendarGrid
                                                currentDate={currentDate}
                                                availability={availability.filter(a => a.user_name === currentUser)}
                                                maxPlayers={1}
                                                onDateClick={handleScheduleDateClick}
                                                onDateFocus={setSelectedScheduleDate}
                                                onDateContextMenu={handleContextMenu}
                                                selectedDate={selectedScheduleDate}
                                                getDateAriaLabel={(date, stats) => {
                                                    const status = stats[0]?.status;
                                                    return `${format(date, "EEEE, MMMM do")}. ${currentUser} is ${getStatusLabel(status).toLowerCase()}. Activate to change availability.`;
                                                }}
                                                renderCell={(date: Date, stats: Availability[]) => {
                                                    const status = stats[0]?.status;
                                                    const hasConflict = getOverviewConflicts(format(date, "yyyy-MM-dd")).length > 0;
                                                    return (
                                                        <div className="flex h-full w-full flex-col items-center justify-center gap-1">
                                                            {hasConflict && (
                                                                <AlertTriangle
                                                                    size={12}
                                                                    className="self-end text-amber-600 dark:text-amber-400"
                                                                    aria-label="Scheduling conflict"
                                                                />
                                                            )}
                                                            {status === "Available" && <span className="text-2xl" aria-hidden="true">✅</span>}
                                                            {status === "Maybe" && <span className="text-2xl text-yellow-500" aria-hidden="true">❓</span>}
                                                            {status === "No" && <span className="text-2xl text-red-500" aria-hidden="true">✕</span>}
                                                            {!status && <span className="text-xs text-gray-300 dark:text-slate-600">-</span>}
                                                        </div>
                                                    );
                                                }}
                                            />
                                        </div>
                                    </div>

                                    {/* Selected date section (displayed horizontally) */}
                                    <section className="rounded-lg border border-gray-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 animate-in fade-in duration-300">
                                        <div className="border-b border-gray-100 bg-gray-50/50 p-5 dark:border-slate-800 dark:bg-slate-800/50">
                                            <h3 className="text-base font-semibold text-gray-900 dark:text-slate-100">Selected date</h3>
                                            <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">{format(selectedScheduleDate, "EEEE, MMMM d")}</p>
                                        </div>
                                        <div className="p-5 flex flex-col md:flex-row gap-6">
                                            {/* Left Column: Personal status & Change status button */}
                                            <div className="w-full md:w-60 shrink-0 space-y-4">
                                                <div className="rounded-md bg-gray-50 p-3 dark:bg-slate-800/60">
                                                    <div className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-slate-400">Your status</div>
                                                    <div className="mt-1 font-semibold text-gray-900 dark:text-slate-100">{getStatusLabel(selectedPlayerStatus)}</div>
                                                </div>

                                                <button
                                                    onClick={() => handleScheduleDateClick(selectedScheduleDate)}
                                                    className="w-full rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 transition-colors hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
                                                >
                                                    Change my status
                                                </button>
                                            </div>

                                            {/* Right Columns: Group player lists laid out horizontally */}
                                            <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                                                {userGroups.map((group) => {
                                                    const groupPlayers = group.players;
                                                    const groupDateStats = availability.filter((entry) => entry.date === selectedDateStr && entry.group_name === group.name);
                                                    const groupAvailable = groupDateStats
                                                        .filter((entry) => entry.status === "Available" && groupPlayers.includes(entry.user_name))
                                                        .map((entry) => entry.user_name);
                                                    const groupMaybe = groupDateStats
                                                        .filter((entry) => entry.status === "Maybe" && groupPlayers.includes(entry.user_name))
                                                        .map((entry) => entry.user_name);
                                                    const groupUnavailable = groupDateStats
                                                        .filter((entry) => entry.status === "No" && groupPlayers.includes(entry.user_name))
                                                        .map((entry) => entry.user_name);
                                                    const groupPending = groupPlayers.filter(
                                                        (player) => !groupDateStats.find((entry) => entry.user_name === player && entry.status)
                                                    );

                                                    return (
                                                        <div key={group.name} className="border-t pt-4 sm:border-t-0 sm:pt-0 border-gray-200 sm:border-t-0 dark:border-slate-800 space-y-3">
                                                            <div className="flex justify-between items-center border-b border-gray-100 dark:border-slate-800 pb-2">
                                                                <span className="font-semibold text-sm text-gray-900 dark:text-slate-100">⚔️ {group.name}</span>
                                                                <span className="text-xs font-semibold bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-200 px-2 py-0.5 rounded">
                                                                    {groupAvailable.length}/{groupPlayers.length}
                                                                </span>
                                                            </div>
                                                            <div className="space-y-3 text-sm">
                                                                 <div>
                                                                     <div className="mb-1 font-medium text-green-700 dark:text-green-400">Available</div>
                                                                     <div className="flex flex-wrap gap-1.5">
                                                                         {groupAvailable.length > 0 ? groupAvailable.map((player) => (
                                                                             <span key={player} className="rounded border border-green-200 bg-green-50 px-2 py-0.5 text-xs text-green-800 dark:border-green-800 dark:bg-green-900/30 dark:text-green-300">{player}</span>
                                                                         )) : <span className="text-xs italic text-gray-400">None</span>}
                                                                     </div>
                                                                 </div>
                                                                 <div>
                                                                     <div className="mb-1 font-medium text-yellow-700 dark:text-yellow-400">Maybe</div>
                                                                     <div className="flex flex-wrap gap-1.5">
                                                                         {groupMaybe.length > 0 ? groupMaybe.map((player) => (
                                                                             <span key={player} className="rounded border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-xs text-yellow-800 dark:border-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">{player}</span>
                                                                         )) : <span className="text-xs italic text-gray-400">None</span>}
                                                                     </div>
                                                                 </div>
                                                                 <div>
                                                                     <div className="mb-1 font-medium text-red-700 dark:text-red-400">Unavailable</div>
                                                                     <div className="flex flex-wrap gap-1.5">
                                                                         {groupUnavailable.length > 0 ? groupUnavailable.map((player) => (
                                                                             <span key={player} className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-800 dark:border-red-800 dark:bg-green-900/30 dark:text-red-300">{player}</span>
                                                                         )) : <span className="text-xs italic text-gray-400">None</span>}
                                                                     </div>
                                                                 </div>
                                                                 {groupPending.length > 0 && (
                                                                     <div>
                                                                         <div className="mb-1 font-medium text-gray-600 dark:text-slate-300">Pending</div>
                                                                         <div className="flex flex-wrap gap-1.5">
                                                                             {groupPending.map((player) => (
                                                                                 <span key={player} className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">{player}</span>
                                                                             ))}
                                                                         </div>
                                                                     </div>
                                                                 )}
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </section>
                                </section>

                                <aside className="space-y-6">
                                    <section className="rounded-lg border border-gray-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
                                        <div className="border-b border-gray-100 bg-gray-50/50 p-5 dark:border-slate-800 dark:bg-slate-800/50">
                                            <h3 className="text-base font-semibold text-gray-900 dark:text-slate-100">Best dates</h3>
                                        </div>
                                        <div className="space-y-2 p-5">
                                            {bestDates.slice(0, 5).length > 0 ? bestDates.slice(0, 5).map((day) => {
                                                const conflictDescriptions = getConflictDescriptions(day.conflicts);
                                                const conflictTitle = conflictDescriptions.join("\n");

                                                return (
                                                    <button
                                                        key={`${day.groupName}-${day.dateStr}`}
                                                        onClick={() => setSelectedScheduleDate(day.date)}
                                                        className="flex w-full items-start justify-between gap-3 rounded-md border border-gray-200 px-3 py-2 text-left transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/70 dark:border-slate-700 dark:hover:bg-slate-800"
                                                    >
                                                        <span className="min-w-0 space-y-1">
                                                            <span className="block text-sm font-medium text-gray-900 dark:text-slate-100">{format(day.date, "EEE, MMM d")}</span>
                                                            {conflictDescriptions.length > 0 ? (
                                                                <span
                                                                    className="block space-y-0.5 text-xs text-amber-700 dark:text-amber-400"
                                                                    title={`Scheduling conflict:\n${conflictTitle}`}
                                                                >
                                                                    {conflictDescriptions.map((description) => (
                                                                        <span key={description} className="flex gap-1.5">
                                                                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                                                                            <span>{description}</span>
                                                                        </span>
                                                                    ))}
                                                                </span>
                                                            ) : (
                                                                <span className="block text-xs text-gray-500 dark:text-slate-400">No overlap warning</span>
                                                            )}
                                                        </span>
                                                        {day.summary && (
                                                            <span
                                                                className={clsx(
                                                                    "max-w-[12rem] rounded px-2 py-1 text-right text-xs leading-snug",
                                                                    day.summary.isReady
                                                                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                                                        : "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                                                                )}
                                                            >
                                                                <span className="block font-semibold">{day.summary.title}</span>
                                                                {day.summary.detail && (
                                                                    <span className="block text-[11px] font-medium opacity-90">{day.summary.detail}</span>
                                                                )}
                                                            </span>
                                                        )}
                                                    </button>
                                                );
                                            }) : (
                                                <div className="rounded-md border border-dashed border-gray-200 p-3 text-sm text-gray-500 dark:border-slate-700 dark:text-slate-400">
                                                    No available dates marked yet.
                                                </div>
                                            )}
                                        </div>
                                    </section>

                                </aside>
                            </div>

                            {userGroups.length > 0 && (
                                <div className="mt-8 pt-8 border-t border-gray-100 dark:border-slate-800 animate-in fade-in slide-in-from-bottom-4 duration-300">
                                    <h3 className="text-lg font-bold text-gray-900 dark:text-slate-100 mb-4 flex items-center gap-2">
                                        ⚔️ Group Availability
                                    </h3>
                                    <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
                                        {userGroups.map((group) => (
                                            <section key={group.name} className="rounded-lg border border-gray-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
                                                <div className="border-b border-gray-100 bg-gray-50/50 p-5 dark:border-slate-800 dark:bg-slate-800/50">
                                                    <h3 className="text-base font-semibold text-gray-900 dark:text-slate-100">{group.name} Availability</h3>
                                                </div>
                                                <div className="p-4">
                                                    <CalendarGrid
                                                        currentDate={currentDate}
                                                        availability={allAvailability}
                                                        maxPlayers={group.players.length}
                                                        onDateClick={setSelectedScheduleDate}
                                                        onDateFocus={setSelectedScheduleDate}
                                                        selectedDate={selectedScheduleDate}
                                                        renderCell={createOverviewCellRenderer(group.name, group.players.length)}
                                                    />
                                                </div>
                                            </section>
                                        ))}
                                    </div>
                                </div>
                            )}
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
                            className="fixed z-50 bg-white dark:bg-slate-800 rounded-lg shadow-xl border border-gray-200 dark:border-slate-700 py-1 w-48 animate-in fade-in zoom-in-95 duration-100"
                            style={{ top: contextMenu.y, left: contextMenu.x }}
                        >
                            <div className="px-3 py-2 border-b border-gray-100 dark:border-slate-700 text-xs font-bold text-gray-400 uppercase tracking-wider bg-gray-50/50 dark:bg-slate-800/50">
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
                                className="w-full text-left px-4 py-2 hover:bg-gray-50 dark:hover:bg-slate-700 text-gray-500 dark:text-slate-400 text-sm flex items-center gap-2"
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
                        <div className="fixed z-[70] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white dark:bg-slate-900 rounded-lg shadow-2xl p-6 w-[90%] max-w-lg border border-gray-100 dark:border-slate-800 animate-in fade-in zoom-in-95 duration-200">
                            <div className="flex justify-between items-center mb-6">
                                <h2 className="text-xl font-bold text-gray-900 dark:text-slate-100 flex items-center gap-2">
                                    <span>📅</span> {format(dateDetails.date, 'EEEE, MMMM do')}
                                </h2>
                                <button
                                    onClick={() => setDateDetails({ ...dateDetails, isOpen: false })}
                                    className="p-1 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-full text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors"
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

                                    if (activeViewMode === "OVERVIEW_CROSS") {
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

                                    const ListBlock = ({ title, icon, color, list }: DayStatusListProps) => (
                                        <div className={`border rounded-lg p-3 ${color} bg-opacity-50`}>
                                            <h4 className="font-bold text-sm mb-2 flex items-center gap-1.5 opacity-90">
                                                <span>{icon}</span> {title} <span className="opacity-60 ml-auto text-xs">({list.length})</span>
                                            </h4>
                                            {list.length > 0 ? (
                                                <div className="flex flex-wrap gap-1.5">
                                                    {list.map((p: string) => (
                                                        <span key={p} className="bg-white/80 dark:bg-slate-800/80 px-2 py-0.5 rounded text-xs font-medium shadow-sm border border-black/5 dark:border-white/10">
                                                            {p}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : <span className="text-xs opacity-50 italic">None</span>}
                                        </div>
                                    );

                                    return (
                                        <>
                                            <ListBlock title="Available" icon="✅" color="bg-green-50 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800" list={available} />
                                            <ListBlock title="Maybe" icon="❓" color="bg-yellow-50 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800" list={maybe} />
                                            <ListBlock title="No" icon="✕" color="bg-red-50 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800" list={no} />
                                            <ListBlock title="Pending" icon="⏳" color="bg-gray-50 text-gray-600 dark:bg-slate-800/50 dark:text-slate-400 border-gray-200 dark:border-slate-700" list={pending} />
                                        </>
                                    );
                                })()}
                            </div>
                        </div>
                    </>
                )}

                {/* SYNC TOAST */}
                {syncSuccessMessage && (
                    <div className="fixed bottom-6 right-6 z-50 bg-green-600 dark:bg-green-700 text-white px-4 py-3 rounded-lg shadow-xl flex items-center gap-2 animate-in fade-in slide-in-from-bottom-8 duration-300">
                        <span>✅</span>
                        <span className="font-medium">{syncSuccessMessage}</span>
                    </div>
                )}
            </main >
        </div >
    )
}
