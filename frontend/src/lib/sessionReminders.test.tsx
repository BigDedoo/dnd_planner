import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionReminderForm, reminderOptions } from "../components/SessionReminderSettings";
import { fetchNotificationPreferences, updateImportantSessionEmails, updateNotificationPreferences } from "../services/api";

vi.mock("@/components/AppShell", () => ({ SurfacePanel: "section" }));
afterEach(() => vi.unstubAllGlobals());

describe("personal session reminders", () => {
    const props = { value: 1440 as const, hasEmail: true, loading: false, saving: false, disabled: false, error: null, notice: null, onChange: vi.fn(), onSave: vi.fn() };

    it("shows the one-day default, all choices and Off", () => {
        const html = renderToStaticMarkup(createElement(SessionReminderForm, props));
        expect(html).toContain('<option value="1440" selected="">1 day before</option>');
        for (const option of reminderOptions) expect(html).toContain(option.label);
        expect(reminderOptions.map(option => option.value)).toEqual([null, 60, 180, 720, 1440, 4320, 10080]);
        expect(html).toContain("If you haven&#x27;t RSVP&#x27;d, we&#x27;ll ask you to respond instead.");
        expect(html).toContain("Sessions you declined");
        expect(html).toContain("Important session updates by email");
        expect(html).toContain('<option value="on" selected="">On</option>');
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, importantEmailsEnabled: false }))).toContain('<option value="off" selected="">Off</option>');
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, value: null }))).toContain('<option value="off" selected="">Off</option>');
    });

    it("shows loading, saving, success, validation error and missing-email states", () => {
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, loading: true }))).toContain("Loading reminder preference");
        const saving = renderToStaticMarkup(createElement(SessionReminderForm, { ...props, saving: true }));
        expect(saving).toContain("Saving…");
        expect(saving).toContain('disabled=""');
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, notice: "Session reminder updated." }))).toContain("Session reminder updated.");
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, error: "Unsupported reminder", hasEmail: false }))).toContain('role="alert"');
        expect(renderToStaticMarkup(createElement(SessionReminderForm, { ...props, hasEmail: false }))).toContain("Delivery requires an email on your sign-in account");
    });

    it("loads the current preference with authentication and saves a lead or Off", async () => {
        const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ session_reminder_minutes: 1440, important_session_emails_enabled: true })));
        vi.stubGlobal("fetch", fetcher);
        expect(await fetchNotificationPreferences("token")).toEqual({ session_reminder_minutes: 1440, important_session_emails_enabled: true });
        expect(fetcher).toHaveBeenCalledWith("/api/me/notification-preferences", { headers: { Authorization: "Bearer token" }, cache: "no-store" });
        for (const value of [180, null] as const) {
            fetcher.mockResolvedValue(new Response(JSON.stringify({ session_reminder_minutes: value })));
            expect(await updateNotificationPreferences(value, "token")).toEqual({ session_reminder_minutes: value });
            const request = fetcher.mock.lastCall?.[1];
            expect(request.method).toBe("PATCH");
            expect(JSON.parse(request.body)).toEqual({ session_reminder_minutes: value });
            expect(request.headers.Authorization).toBe("Bearer token");
        }
        for (const enabled of [false, true]) {
            fetcher.mockResolvedValue(new Response(JSON.stringify({ session_reminder_minutes: 180, important_session_emails_enabled: enabled })));
            expect((await updateImportantSessionEmails(enabled, "token")).important_session_emails_enabled).toBe(enabled);
            expect(JSON.parse(fetcher.mock.lastCall?.[1].body)).toEqual({ important_session_emails_enabled: enabled });
        }
    });

    it("surfaces backend errors without replacing them with a success", async () => {
        vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: [{ msg: "Unsupported reminder" }] }), { status: 422 }))));
        await expect(updateNotificationPreferences(60, "token")).rejects.toThrow("Unsupported reminder");
        await expect(fetchNotificationPreferences("token")).rejects.toThrow();
        await expect(updateImportantSessionEmails(false, "token")).rejects.toThrow("Unsupported reminder");
    });
});
