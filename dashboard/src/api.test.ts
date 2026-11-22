import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi, query } from "./api";

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

describe("createApi", () => {
  it("sends the admin key as a header, never in the URL, and omits cookies", async () => {
    const fetcher = fakeFetch(200, []);
    await createApi("secret-key", fetcher).audit({ decision: "deny", agent_name: "" });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/v1/audit?decision=deny");
    expect(String(url)).not.toContain("secret-key");
    expect((init?.headers as Record<string, string>)["X-Admin-Key"]).toBe("secret-key");
    expect(init?.credentials).toBe("omit");
    expect(init?.cache).toBe("no-store");
  });

  it("posts JSON with a content type when there is a body", async () => {
    const fetcher = fakeFetch(201, { id: "1", api_key: "ag_x" });
    await createApi("k", fetcher).registerAgent("billing-agent", "");
    const init = fetcher.mock.calls[0][1]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ name: "billing-agent", description: null });
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("escapes ids in paths", async () => {
    const fetcher = fakeFetch(200, {});
    await createApi("k", fetcher).approve("../agents");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/approvals/..%2Fagents/approve");
  });

  it("turns error responses into ApiError with the server's detail", async () => {
    const api = createApi("k", fakeFetch(409, { detail: "Approval is used" }));
    await expect(api.approve("1")).rejects.toEqual(new ApiError(409, "Approval is used"));
  });

  it("calls a configured API origin", async () => {
    const fetcher = fakeFetch(200, {});
    await createApi("k", fetcher, "https://api.example.com").verify();
    expect(fetcher.mock.calls[0][0]).toBe("https://api.example.com/api/v1/audit/verify");
  });

  it("refuses a non-JSON answer, such as a static host's own page", async () => {
    const html = vi.fn(async () => new Response("<!doctype html>", { headers: { "Content-Type": "text/html" } }));
    await expect(createApi("k", html).overview()).rejects.toMatchObject({ status: 0 });
  });

  it("reports a backend that does not answer", async () => {
    const api = createApi("k", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(api.verify()).rejects.toMatchObject({ status: 0 });
  });
});

describe("query", () => {
  it("drops empty values", () => {
    expect(query({ a: "", b: undefined, c: 0, d: "x" })).toBe("?c=0&d=x");
    expect(query({})).toBe("");
  });
});
