import type { Availability } from "@/services/api";

export interface BestDateRecommendation {
    day: string;
    available: number;
    maybe: number;
    unavailable: number;
    answered: number;
}

export function rankBestDates(
    entries: Availability[],
    memberCount: number,
    fromDay: string,
    limit = 3
): BestDateRecommendation[] {
    const byDay = new Map<string, BestDateRecommendation>();
    for (const entry of entries) {
        if (entry.date < fromDay) continue;
        const current = byDay.get(entry.date) ?? {
            day: entry.date,
            available: 0,
            maybe: 0,
            unavailable: 0,
            answered: 0,
        };
        if (entry.status === "Available") current.available += 1;
        if (entry.status === "Maybe") current.maybe += 1;
        if (entry.status === "No") current.unavailable += 1;
        current.answered = current.available + current.maybe + current.unavailable;
        byDay.set(entry.date, current);
    }
    return [...byDay.values()]
        .filter((entry) => entry.available > 0 || entry.maybe > 0)
        .sort((left, right) =>
            right.available - left.available ||
            right.maybe - left.maybe ||
            left.unavailable - right.unavailable ||
            right.answered - left.answered ||
            left.day.localeCompare(right.day)
        )
        .slice(0, limit)
        .map((entry) => ({ ...entry, answered: Math.min(entry.answered, memberCount) }));
}

export function bestDateReason(
    recommendation: BestDateRecommendation,
    memberCount: number
): string {
    if (recommendation.available === memberCount) {
        return `${recommendation.available}/${memberCount} available`;
    }
    const parts = [`${recommendation.available} available`];
    if (recommendation.maybe > 0) parts.push(`${recommendation.maybe} maybe`);
    return parts.join(", ");
}
