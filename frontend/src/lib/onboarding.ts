export function safeOnboardingNext(value: string | null): string {
    if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
        return "/app";
    }
    try {
        const destination = new URL(value, "https://dnd-planner.invalid");
        const decodedPathname = decodeURIComponent(destination.pathname);
        if (destination.origin !== "https://dnd-planner.invalid" || decodedPathname.startsWith("//") || decodedPathname.includes("\\")) {
            return "/app";
        }
        return `${destination.pathname}${destination.search}${destination.hash}`;
    } catch {
        return "/app";
    }
}
