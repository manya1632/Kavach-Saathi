const API = "/agent-api/v1";
const TOKEN_KEY = "kavach.auth.v1";

export function loadAuthSession() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(TOKEN_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveAuthSession(session) {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
}

export async function request(path, options = {}) {
  const session = loadAuthSession();
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "ngrok-skip-browser-warning": "1",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    saveAuthSession(null);
    window.dispatchEvent(new CustomEvent("kavach:session-expired"));
    throw new Error("Session expired — please log in again");
  }
  const raw = await response.text();
  let payload = {};
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = { detail: raw.startsWith("Internal Server Error") ? "The server could not complete this request" : raw };
    }
  }
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

export function post(path, body) {
  return request(path, { method: "POST", body: JSON.stringify(body) });
}

/**
 * listings/reviews/returns are real async workflows now (Agents 1/2/4/8 call real
 * models that can take real minutes) -- the endpoint returns `status:"queued"`
 * immediately instead of the finished result. This posts, then polls
 * GET /runs/{run_id} until the workflow reaches a terminal status, so callers can keep
 * treating the call as "await postAndPoll(...) -> finished envelope" like before.
 */
export async function postAndPoll(path, body, { onTick, intervalMs = 1200, timeoutMs = 20 * 60 * 1000 } = {}) {
  const envelope = await post(path, body);
  if (envelope.status !== "queued" && envelope.status !== "running") return envelope;
  const deadline = Date.now() + timeoutMs;
  let current = envelope;
  while (Date.now() < deadline) {
    onTick?.(current);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    current = await request(`/runs/${envelope.run_id}`);
    if (current.status !== "queued" && current.status !== "running") return current;
  }
  throw new Error("This check is taking longer than expected — please try again shortly.");
}

export function patch(path, params) {
  const query = params ? `?${new URLSearchParams(params).toString()}` : "";
  return request(`${path}${query}`, { method: "PATCH" });
}

export function get(path) {
  return request(path);
}

export function patchJson(path, body) {
  return request(path, { method: "PATCH", body: JSON.stringify(body) });
}

export function del(path) {
  return request(path, { method: "DELETE" });
}

export const getCart = () => get("/cart");
export const addToCart = (productVariantId, qty = 1) => post("/cart", { product_variant_id: productVariantId, qty });
export const updateCartItem = (itemId, qty) => patchJson(`/cart/${itemId}`, { qty });
export const removeCartItem = (itemId) => del(`/cart/${itemId}`);
export const createOrder = (addressId, paymentMode) => post("/orders", { address_id: addressId, payment_mode: paymentMode });
export const verifyPayment = (orderId, payload) => post(`/orders/${orderId}/verify-payment`, payload);
export const listMyOrders = () => get("/orders");
export const getWishlist = () => get("/wishlist");
export const addWishlist = (productId) => post(`/wishlist/${productId}`, {});
export const removeWishlist = (productId) => del(`/wishlist/${productId}`);
export const listMyReturns = () => get("/returns");
export const createReturnRequest = (orderId, reason) => post("/returns", { order_id: orderId, reason });
export const createReview = (payload) => post("/reviews", payload);

export function assetUrl(path) {
  if (!path) return "";
  if (path.startsWith("/mock-assets")) return path;
  if (path.startsWith("assets/mock/")) return `/mock-assets/${path.slice("assets/mock/".length)}`;
  return `/mock-assets/${path}`;
}

export async function signup(payload) {
  const session = await post("/auth/signup", payload);
  saveAuthSession(session);
  return session;
}

export async function login(identifier, password) {
  const session = await post("/auth/login", { identifier, password });
  saveAuthSession(session);
  return session;
}

export function logout() {
  saveAuthSession(null);
}
