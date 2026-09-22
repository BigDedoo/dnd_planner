import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

const { handlers } = vi.hoisted(() => ({ handlers: [] as Array<(auth: { protect: () => Promise<void> }, req: NextRequest) => Promise<void>> }));
vi.mock("@clerk/nextjs/server", async (importOriginal) => {
    const original = await importOriginal<typeof import("@clerk/nextjs/server")>();
    return { ...original, clerkMiddleware: (handler: typeof handlers[number]) => { handlers.push(handler); return handler; } };
});
import "../proxy";

describe("privacy route access", () => {
    it("keeps privacy and support public while protecting the account page", async () => {
        const protect = vi.fn().mockResolvedValue(undefined);
        for (const route of ["/privacy", "/support"]) {
            await handlers[0]({ protect }, new NextRequest(`https://example.test${route}`));
        }
        expect(protect).not.toHaveBeenCalled();
        await handlers[0]({ protect }, new NextRequest("https://example.test/account"));
        expect(protect).toHaveBeenCalledOnce();
    });
});
