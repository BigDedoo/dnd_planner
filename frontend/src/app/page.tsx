"use client";

import { useEffect, useState } from "react";
import { format, addMonths, subMonths } from "date-fns";
import { fetchGroups, fetchAvailability, updateAvailability, Group, Availability } from "@/services/api";
import { CalendarGrid } from "@/components/CalendarGrid";
import { ChevronLeft, ChevronRight, User, Users } from "lucide-react";
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
        // Default to first group
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
    // Filter out old entry for this user/date
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
    <div className="flex flex-col md:flex-row min-h-screen bg-neutral-950 text-neutral-200">

      {/* SIDEBAR (Desktop) / TOPBAR (Mobile) */}
      <aside className="w-full md:w-64 bg-neutral-900 border-b md:border-r border-neutral-800 p-4 shrink-0">
        <h1 className="text-xl font-bold mb-6 flex items-center gap-2 text-indigo-400">
          <span className="text-2xl">🎲</span> DnD Planner
        </h1>

        <div className="mb-6">
          <label className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2 block">
            Select Group
          </label>
          <div className="space-y-1">
            {groups.map(g => (
              <button
                key={g.name}
                onClick={() => setSelectedGroup(g.name)}
                className={clsx(
                  "w-full text-left px-3 py-2 rounded-md text-sm transition",
                  selectedGroup === g.name ? "bg-indigo-900/30 text-indigo-300" : "hover:bg-neutral-800"
                )}
              >
                {g.name}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-6">
          <label className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2 block">
            Who are you?
          </label>
          {selectedGroup ? (
            <div className="grid grid-cols-2 md:grid-cols-1 gap-2">
              {currentGroupPlayers.map(player => (
                <button
                  key={player}
                  onClick={() => setCurrentUser(player)}
                  className={clsx(
                    "px-3 py-2 rounded-md text-sm text-left border transition flex items-center gap-2",
                    currentUser === player
                      ? "bg-green-900/20 border-green-800 text-green-400"
                      : "bg-neutral-800 border-transparent hover:bg-neutral-700"
                  )}
                >
                  <User size={14} />
                  {player}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-sm text-neutral-600">Select a group...</p>
          )}
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="flex-1 p-4 md:p-8 overflow-y-auto">
        <div className="max-w-4xl mx-auto">
          {/* Header / Date Controls */}
          <header className="flex items-center justify-between mb-8">
            <div>
              <h2 className="text-2xl font-bold text-white mb-1">
                {format(currentDate, "MMMM yyyy")}
              </h2>
              <p className="text-sm text-neutral-400 flex items-center gap-1">
                Viewing <strong className="text-indigo-400">{selectedGroup}</strong>
                {currentUser && <span>as <strong className="text-green-400">{currentUser}</strong></span>}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setCurrentDate(subMonths(currentDate, 1))}
                className="p-2 hover:bg-neutral-800 rounded-full transition"
              >
                <ChevronLeft />
              </button>
              <button
                onClick={() => setCurrentDate(addMonths(currentDate, 1))}
                className="p-2 hover:bg-neutral-800 rounded-full transition"
              >
                <ChevronRight />
              </button>
            </div>
          </header>

          {/* Layout: Desktop = Side-by-Side, Mobile = Stacked */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

            {/* LEFT: Personal Availability */}
            <section className={clsx("transition-opacity", !currentUser && "opacity-50 pointer-events-none")}>
              <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <User className="text-indigo-400" /> Your Input
              </h3>
              <div className="bg-neutral-900/50 p-4 rounded-xl border border-neutral-800">
                <CalendarGrid
                  currentDate={currentDate}
                  availability={availability.filter(a => a.user_name === currentUser)}
                  maxPlayers={1} // Self
                  onDateClick={handleToggleStatus}
                  renderCell={(date, stats) => {
                    const status = stats[0]?.status;
                    let icon = null;
                    if (status === 'Available') icon = "✅";
                    else if (status === 'Maybe') icon = "❓";
                    else if (status === 'No') icon = "❌";

                    return <div className="mt-1 text-lg">{icon}</div>
                  }}
                />
              </div>
            </section>

            {/* RIGHT: Team Overview */}
            <section>
              <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Users className="text-emerald-400" /> Team Overview
              </h3>
              <div className="bg-neutral-900/50 p-4 rounded-xl border border-neutral-800">
                <CalendarGrid
                  currentDate={currentDate}
                  availability={availability}
                  maxPlayers={maxPlayers}
                  onDateClick={() => { }} // Read only
                />
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
