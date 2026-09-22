/** Accept only operator contact links; no executable schemes or URL credentials. */
export function supportContactUrl(value: string | undefined): string | null {
    const candidate = value?.trim();
    if (!candidate || /[\u0000-\u0020\u007f]/.test(candidate)) return null;
    try {
        const url = new URL(candidate);
        if (url.protocol === "https:" && url.hostname && !url.username && !url.password) {
            return url.href;
        }
        if (url.protocol === "mailto:" && /^[^/?#@]+@[^/?#@]+$/.test(url.pathname)
            && !/%0[ad]/i.test(candidate)) return url.href;
    } catch {
        // Invalid or absent config uses the same neutral, build-safe fallback.
    }
    return null;
}
