const API = "/agent-api/v1";
// Separate storage per side of the app, keyed by which route is currently loaded --
// the Seller Portal (/seller/*) and the buyer storefront used to share one
// "kavach.auth.v1" key, so having both open in different tabs of the same browser
// (a very normal thing to do while testing) meant whichever tab last touched
// localStorage silently overwrote the other's session. A buyer tab could end up
// making API calls with a seller's token (or vice versa) with no visible sign
// anything was wrong until a role-gated endpoint 403'd with a raw "Insufficient
// role" error. Keying storage by route means each side keeps its own persistent
// login independent of what's happening in the other tab.
const BUYER_TOKEN_KEY = "kavach.auth.buyer.v1";
const SELLER_TOKEN_KEY = "kavach.auth.seller.v1";

function tokenKey() {
  if (typeof window === "undefined") return BUYER_TOKEN_KEY;
  return window.location.pathname.startsWith("/seller") ? SELLER_TOKEN_KEY : BUYER_TOKEN_KEY;
}

export function loadAuthSession() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(tokenKey());
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveAuthSession(session) {
  if (typeof window === "undefined") return;
  const key = tokenKey();
  if (!session) {
    window.localStorage.removeItem(key);
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(session));
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
    const errMsg = formatErrorDetail(payload.detail) || payload.error || `Request failed (${response.status})`;
    const error = new Error(errMsg);
    error.detail = payload.detail;
    throw error;
  }
  return payload;
}

export function formatErrorDetail(detail) {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object") {
    if (detail.message) {
      let msg = detail.message;
      if (detail.errors && typeof detail.errors === "object") {
        const errDetails = Object.entries(detail.errors)
          .map(([field, err]) => `${field}: ${formatErrorDetail(err)}`)
          .join(", ");
        if (errDetails) msg += ` (${errDetails})`;
      }
      return msg;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((err) => {
          const field = err.loc ? err.loc.filter(loc => loc !== "body" && loc !== "query").join(".") : "field";
          return `${field}: ${err.msg}`;
        })
        .join(", ");
    }
    return Object.entries(detail)
      .map(([key, val]) => `${key}: ${formatErrorDetail(val)}`)
      .join(", ");
  }
  return String(detail);
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
export const createReturnRequest = (orderId, productId, reason, returnType = "refund") => post("/returns", { order_id: orderId, product_id: productId, reason, return_type: returnType });
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
