const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? error.message : "Could not reach the API.",
      0,
      "NETWORK_ERROR",
      {},
    );
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = payload?.error;
    throw new ApiError(
      apiError?.message || `Request failed with status ${response.status}.`,
      response.status,
      apiError?.code || "HTTP_ERROR",
      apiError?.details || {},
    );
  }
  return payload;
}

export async function fetchAll(path, filters = {}) {
  const query = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });

  const items = [];
  let offset = 0;
  let total = Infinity;
  while (offset < total) {
    query.set("limit", "100");
    query.set("offset", String(offset));
    const page = await apiRequest(`${path}?${query.toString()}`);
    if (!Array.isArray(page?.items) || typeof page.total !== "number") {
      throw new ApiError("The API returned an invalid paginated response.", 0, "INVALID_RESPONSE", {});
    }
    items.push(...page.items);
    total = page.total;
    offset += page.items.length;
    if (page.items.length === 0) break;
  }
  return items;
}

export function postJson(path, data) {
  return apiRequest(path, { method: "POST", body: JSON.stringify(data) });
}
