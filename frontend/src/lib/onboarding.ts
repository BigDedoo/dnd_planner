export function safeOnboardingNext(value: string | null): string {
    return value && value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}
