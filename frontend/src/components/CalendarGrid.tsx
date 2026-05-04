import { format, startOfMonth, endOfMonth, eachDayOfInterval, getDay } from 'date-fns';
import { Availability } from '@/services/api';
import clsx from 'clsx';

interface CalendarProps {
    currentDate: Date;
    availability: Availability[];
    maxPlayers: number;
    onDateClick: (date: Date) => void;
    onDateContextMenu?: (date: Date, e: React.MouseEvent) => void;
    renderCell?: (date: Date, stats: Availability[]) => React.ReactNode;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Helper for Monday-start index
function getDayIndex(date: Date) {
    const day = getDay(date);
    return day === 0 ? 6 : day - 1;
}

export function CalendarGrid({ currentDate, availability, maxPlayers, onDateClick, onDateContextMenu, renderCell }: CalendarProps) {
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const daysInMonth = eachDayOfInterval({ start: monthStart, end: monthEnd });

    // Padding for start of month
    const startPadding = Array.from({ length: getDayIndex(monthStart) });

    return (
        <div className="w-full">
            {/* Header */}
            <div className="grid grid-cols-7 gap-2 mb-2">
                {DAYS.map(day => (
                    <div key={day} className="text-center text-xs font-bold text-gray-500 py-2">
                        {day}
                    </div>
                ))}
            </div>

            {/* Grid */}
            <div className="grid grid-cols-7 gap-2 auto-rows-fr">
                {startPadding.map((_, i) => (
                    <div key={`pad-${i}`} className="min-h-[80px]" />
                ))}

                {daysInMonth.map(date => {
                    const dateStr = format(date, 'yyyy-MM-dd');
                    const dayStats = availability.filter(a => a.date === dateStr);
                    const isToday = format(new Date(), 'yyyy-MM-dd') === dateStr;

                    return (
                        <div key={dateStr} className="relative">
                            <button
                                className={clsx(
                                    "w-full h-full min-h-[80px] p-2 flex flex-col items-start justify-start gap-1 font-normal text-left transition-colors rounded-md border",
                                    isToday ? "border-blue-500 bg-blue-50 dark:bg-blue-900/30" : "border-gray-200 dark:border-slate-700 hover:border-gray-400 dark:hover:border-slate-500 bg-white dark:bg-slate-900"
                                )}
                                onClick={() => onDateClick(date)}
                                onContextMenu={(e) => {
                                    if (onDateContextMenu) {
                                        e.preventDefault();
                                        onDateContextMenu(date, e);
                                    }
                                }}
                            >
                                <span className={clsx("text-xs font-mono", isToday ? "text-blue-600 font-bold" : "text-gray-400")}>
                                    {format(date, 'd')}
                                </span>

                                <div className="w-full h-full flex items-center justify-center mt-1">
                                    {renderCell ? renderCell(date, dayStats) : (
                                        <DefaultStatusIndicator stats={dayStats} max={maxPlayers} />
                                    )}
                                </div>
                            </button>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function DefaultStatusIndicator({ stats, max }: { stats: Availability[], max: number }) {
    const available = stats.filter(s => s.status === 'Available').length;

    // Logic:
    // Full team -> Green Badge
    // > 50% -> Yellow Badge
    // > 0 -> Gray Badge

    if (available === max) return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">{available}/{max}</span>;
    if (available >= max / 2) return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800">{available}/{max}</span>;
    if (available > 0) return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">{available}/{max}</span>;

    return <span className="text-xs text-gray-300">-</span>;
}
