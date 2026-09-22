import { afterEach, expect, it, vi } from "vitest";
import { updateGroupName, updateGroupSettings } from "@/services/api";

afterEach(() => vi.unstubAllGlobals());

it("sends a partial timezone update and preserves the rename helper", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "group", timezone: "Europe/Paris" })));
    vi.stubGlobal("fetch", fetchMock);
    const updated = await updateGroupSettings("group", { timezone: "Europe/Paris" }, "test-token");
    expect(updated.timezone).toBe("Europe/Paris");
    expect(fetchMock).toHaveBeenCalledWith("/api/groups/group", expect.objectContaining({ method: "PATCH", body: '{"timezone":"Europe/Paris"}', headers: expect.objectContaining({ Authorization: "Bearer test-token" }) }));
    fetchMock.mockResolvedValue(new Response("{}"));
    await updateGroupName("group", "Renamed");
    expect(fetchMock).toHaveBeenLastCalledWith("/api/groups/group", expect.objectContaining({ body: '{"name":"Renamed"}' }));
});

it("surfaces the backend DST rejection without changing any session fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Session time is ambiguous in Europe/Paris" }), { status: 422 })));
    await expect(updateGroupSettings("group", { timezone: "Europe/Paris" })).rejects.toThrow("ambiguous in Europe/Paris");
});

it("shows readable IANA validation feedback", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "Use a valid IANA timezone" }] }), { status: 422 })));
    await expect(updateGroupSettings("group", { timezone: "Not/AZone" })).rejects.toThrow("Use a valid IANA timezone");
});
