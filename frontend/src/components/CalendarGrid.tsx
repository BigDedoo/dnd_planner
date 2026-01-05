import { format, startOfMonth, endOfMonth, eachDayOfInterval, getDay, isSameDay } from 'date-fns';
import { Availability } from '@/services/api';

interface CalendarProps {
    currentDate: Date;
    availability: Availability[];
    maxPlayers: number;
    onDateClick: (date: Date) => void;
    renderCell?: (date: Date, stats: Availability[]) => React.ReactNode;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Helper for Monday-start index
function getDayIndex(date: Date) {
    const day = getDay(date);
    return day === 0 ? 6 : day - 1;
}

export function CalendarGrid({ currentDate, availability, maxPlayers, onDateClick, renderCell }: CalendarProps) {
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const daysInMonth = eachDayOfInterval({ start: monthStart, end: monthEnd });

    // Padding for start of month
    const startPadding = Array.from({ length: getDayIndex(monthStart) });

    return (
        <div className="w-full">
            {/* Header */}
            <div className="grid grid-cols-7 gap-1 mb-2">
                {DAYS.map(day => (
                    <div key={day} className="text-center text-xs font-bold text-gray-400 py-1">
                        {day}
                    </div>
                ))}
            </div>

            {/* Grid */}
            <div className="grid grid-cols-7 gap-1 auto-rows-fr">
                {startPadding.map((_, i) => (
                    <div key={`pad-${i}`} className="min-h-[50px]" />
                ))}

                {daysInMonth.map(date => {
                    const dateStr = format(date, 'yyyy-MM-dd');
                    const dayStats = availability.filter(a => a.date === dateStr);

                    return (
                        <button
                            key={dateStr}
                            onClick={() => onDateClick(date)}
                            className="relative min-h-[50px] p-1 border border-gray-800 rounded-md hover:bg-gray-800 transition flex flex-col items-center justify-start text-xs sm:text-sm"
                        >
                            <span className="mb-1 font-semibold">{format(date, 'd')}</span>
                            {renderCell ? renderCell(date, dayStats) : (
                                <DefaultStatusIndicator stats={dayStats} max={maxPlayers} />
                            )}
                        </button>
                    );
                })}
            </div>
        </div>
    );
}

function DefaultStatusIndicator({ stats, max }: { stats: Availability[], max: number }) {
    const available = stats.filter(s => s.status === 'Available').length;
    // const maybe = stats.filter(s => s.status === 'Maybe').length;

    if (available === max) return <span className="text-green-500 text-lg">🟢</span>;
    if (available >= max / 2) return <span className="text-yellow-500 text-lg">🟡</span>;
    if (available > 0) return <span className="text-orange-500 text-lg">🟠</span>;
    return <span className="text-gray-600 text-lg">⚪</span>;
}
