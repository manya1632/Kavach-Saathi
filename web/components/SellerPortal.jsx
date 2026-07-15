"use client";

import {
  BadgeCheck,
  Boxes,
  Check,
  ClipboardList,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Package,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { useEffect, useState } from "react";

import { loadAuthSession, login, logout, post, postAndPoll, request, saveAuthSession, signup } from "@/lib/api";

const CATEGORIES = [
  "Kurti, Saree & Lehenga",
  "Women Western",
  "Lingerie",
  "Men",
  "Kids & Toys",
  "Home & Kitchen",
  "Beauty & Health",
  "Jewellery & Accessories",
  "Bags & Footwear",
];

function SellerAuth({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = mode === "login"
        ? await login(email, password)
        : await signup({ role: "seller", name, business_name: businessName, email, password });
      if (session.user.role !== "seller") {
        saveAuthSession(null);
        throw new Error("This account is not a seller account.");
      }
      onAuthenticated(session);
    } catch (reason) {
      setError(reason.message || "That didn't work — please try again");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="seller-auth-shell">
      <div className="seller-auth-card">
        <div className="seller-brand"><ShieldCheck size={22} /><div><strong>Kavach Saathi</strong><small>Seller Portal</small></div></div>
        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Log in</button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>Sign up</button>
        </div>
        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === "signup" && (
            <>
              <label>Your name<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
              <label>Business name<input value={businessName} onChange={(event) => setBusinessName(event.target.value)} required /></label>
            </>
          )}
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={mode === "signup" ? 8 : 1} /></label>
          {error && <p className="auth-error">{error}</p>}
          <button className="primary-cta wide" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : null} {mode === "login" ? "Log in" : "Create seller account"}</button>
        </form>
      </div>
    </div>
  );
}

function DashboardTab({ profile }) {
  if (!profile) return null;
  return (
    <div className="seller-panel">
      <div className="seller-stat-grid">
        <div><strong>{profile.trust_score ?? "—"}</strong><span>Trust score</span></div>
        <div><strong>{profile.catalog_accuracy_score ?? "—"}</strong><span>Catalog accuracy</span></div>
        <div><strong>{profile.rto_rate ?? "—"}</strong><span>RTO rate</span></div>
        <div><strong>{profile.fraud_flags ?? 0}</strong><span>Fraud flags</span></div>
      </div>
      <div className={`kyc-badge ${profile.digilocker_kyc_status}`}>
        <BadgeCheck size={15} /> DigiLocker KYC: {profile.digilocker_kyc_status.replace("_", " ")}
      </div>
    </div>
  );
}

function AddProductTab({ onCreated }) {
  const [form, setForm] = useState({ title: "", category: CATEGORIES[0], price: "", original_price: "", description: "" });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!file) { setError("Upload a catalogue photo first"); return; }
    setBusy(true);
    setError("");
    setResult(null);
    setProgress("");
    try {
      const presign = await post("/uploads/presign", { kind: "catalogue", filename: file.name, content_type: file.type || "image/png" });
      await fetch(presign.upload_url, { method: "PUT", body: file, headers: { "Content-Type": file.type || "image/png" } });

      const product = await post("/seller/products", {
        title: form.title,
        category: form.category,
        description: form.description,
        price: Number(form.price),
        original_price: Number(form.original_price),
        image_keys: [presign.object_key],
      });

      setProgress("Agent 1 (SAM 2.0 + Nano Banana 2 / Stable Diffusion) and Agent 2 (Claude OCR + CLIP/ResNet-50) are verifying this listing — image generation can take several minutes on CPU.");
      const analysis = await postAndPoll(
        "/listings/analyze",
        { seller_id: product.seller_id, product_id: product.id, image_keys: [presign.object_key], seller_specs: {} },
        { onTick: () => setProgress((current) => current + ".") },
      ).catch((reason) => ({ status: "failed", error: reason.message }));

      setResult({ product, analysis });
      onCreated();
    } catch (reason) {
      setError(reason.message || "Could not create the listing");
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  return (
    <div className="seller-panel">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>Product title<input value={form.title} onChange={(event) => update("title", event.target.value)} required /></label>
        <label>Category
          <select value={form.category} onChange={(event) => update("category", event.target.value)}>
            {CATEGORIES.map((category) => <option key={category} value={category}>{category}</option>)}
          </select>
        </label>
        <label>Description<input value={form.description} onChange={(event) => update("description", event.target.value)} /></label>
        <label>Price (₹)<input type="number" min="1" value={form.price} onChange={(event) => update("price", event.target.value)} required /></label>
        <label>Original price (₹)<input type="number" min="1" value={form.original_price} onChange={(event) => update("original_price", event.target.value)} required /></label>
        <label>Catalogue photo (1–2 images per the plan; upload one to start)<input type="file" accept="image/*" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
        {error && <p className="auth-error">{error}</p>}
        <button className="primary-cta wide" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />} Create listing &amp; run Agent 1 + 2</button>
        {busy && progress && <p className="listing-progress">{progress}</p>}
      </form>
      {result && (
        <div className="listing-result">
          <p><Check size={14} /> Draft product <strong>{result.product.id}</strong> created.</p>
          <p>Agent pipeline status: <strong>{result.analysis.status}</strong>
            {result.analysis.error ? ` — ${result.analysis.error}` : " — see the Inventory tab once specs are verified."}
          </p>
        </div>
      )}
    </div>
  );
}

function InventoryTab({ products, onAddVariant }) {
  const [variantForm, setVariantForm] = useState({});

  function updateVariant(productId, field, value) {
    setVariantForm((current) => ({ ...current, [productId]: { ...current[productId], [field]: value } }));
  }

  return (
    <div className="seller-panel">
      {!products.length && <p className="empty-note">No listings yet — add your first product in the &quot;Add Product&quot; tab.</p>}
      {products.map((product) => (
        <article className="inventory-row" key={product.id}>
          <div>
            <strong>{product.title}</strong>
            <span className={`status-pill ${product.status}`}>{product.status}</span>
            <p>{product.category} · ₹{product.price} · spec source: {product.spec_source}</p>
            {product.stolen_photo_flag && <p className="warn-note">Flagged: possible copied catalogue photo</p>}
          </div>
          <div className="variant-list">
            {product.variants.map((variant) => <span key={variant.id} className="variant-chip">{variant.size}: {variant.stock_qty} units</span>)}
          </div>
          <form
            className="variant-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = variantForm[product.id] || {};
              if (!form.size || !form.stock_qty) return;
              onAddVariant(product.id, { size: form.size, stock_qty: Number(form.stock_qty) });
            }}
          >
            <input placeholder="Size (e.g. M)" value={variantForm[product.id]?.size || ""} onChange={(event) => updateVariant(product.id, "size", event.target.value)} />
            <input placeholder="Stock" type="number" min="0" value={variantForm[product.id]?.stock_qty || ""} onChange={(event) => updateVariant(product.id, "stock_qty", event.target.value)} />
            <button type="submit"><Boxes size={14} /> Add/update variant</button>
          </form>
        </article>
      ))}
    </div>
  );
}

function OrdersTab({ orders, onMark }) {
  return (
    <div className="seller-panel">
      {!orders.length && <p className="empty-note">No orders yet for your listings.</p>}
      {orders.map((order) => (
        <article className="order-row" key={`${order.order_id}-${order.product_id}`}>
          <div><strong>{order.order_id}</strong><span className="status-pill">{order.status}</span></div>
          <p>{order.product_id} · size {order.size || "Standard"} · qty {order.qty} · ₹{order.price_at_purchase}</p>
          <div className="order-actions">
            <button type="button" onClick={() => onMark(order.order_id, "PACKED")}><Package size={13} /> Mark packed</button>
            <button type="button" onClick={() => onMark(order.order_id, "SHIPPED")}><ClipboardList size={13} /> Mark shipped</button>
          </div>
        </article>
      ))}
    </div>
  );
}

function KycTab({ profile, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  async function connect() {
    setBusy(true);
    setNotice("");
    try {
      const redirectUri = `${window.location.origin}/seller/kyc/callback`;
      const response = await request(`/seller/kyc/start?${new URLSearchParams({ redirect_uri: redirectUri })}`, { method: "POST" });
      if (!response.configured) {
        setNotice("DigiLocker isn't configured on this deployment yet (DIGILOCKER_CLIENT_ID/SECRET missing). KYC will stay 'not_started' until real credentials are added — this is not faked as verified.");
        return;
      }
      window.location.href = response.authorize_url;
    } catch (reason) {
      setNotice(reason.message || "Could not start DigiLocker KYC");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="seller-panel">
      <div className={`kyc-badge ${profile?.digilocker_kyc_status}`}><BadgeCheck size={15} /> Status: {profile?.digilocker_kyc_status?.replace("_", " ")}</div>
      <button className="primary-cta wide" type="button" onClick={connect} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Connect DigiLocker</button>
      {notice && <p className="auth-error">{notice}</p>}
      <button type="button" className="secondary-cta" onClick={onRefresh}>Refresh status</button>
    </div>
  );
}

export default function SellerPortal() {
  const [auth, setAuth] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("dashboard");
  const [profile, setProfile] = useState(null);
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [toast, setToast] = useState("");

  useEffect(() => {
    // Reading localStorage must happen post-mount to avoid an SSR/client hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuth(loadAuthSession());
    setReady(true);
  }, []);

  async function refreshAll() {
    const [profileData, productData, orderData] = await Promise.all([
      request("/seller/profile"),
      request("/seller/products"),
      request("/seller/orders"),
    ]);
    setProfile(profileData);
    setProducts(productData);
    setOrders(orderData);
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async data fetch on mount/auth change
    if (auth?.user?.role === "seller") refreshAll().catch((reason) => setToast(reason.message));
  }, [auth]);

  useEffect(() => {
    if (!toast) return undefined;
    const id = window.setTimeout(() => setToast(""), 3000);
    return () => window.clearTimeout(id);
  }, [toast]);

  if (!ready) return null;
  if (!auth?.user || auth.user.role !== "seller") {
    return <SellerAuth onAuthenticated={setAuth} />;
  }

  async function addVariant(productId, payload) {
    try {
      await post(`/seller/products/${productId}/variants`, payload);
      await refreshAll();
      setToast("Variant saved");
    } catch (reason) {
      setToast(reason.message);
    }
  }

  async function markOrder(orderId, status) {
    try {
      await request(`/seller/orders/${orderId}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      await refreshAll();
      setToast(`Order ${orderId} marked ${status.toLowerCase()}`);
    } catch (reason) {
      setToast(reason.message);
    }
  }

  const tabs = [
    { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { key: "add", label: "Add Product", icon: Upload },
    { key: "inventory", label: "Inventory", icon: Boxes },
    { key: "orders", label: "Orders", icon: ClipboardList },
    { key: "kyc", label: "KYC", icon: ShieldCheck },
  ];

  return (
    <div className="seller-portal">
      <header className="seller-header">
        <div className="seller-brand"><ShieldCheck size={20} /><div><strong>Kavach Saathi</strong><small>Seller Portal</small></div></div>
        <button type="button" className="logout-link" onClick={() => { logout(); setAuth(null); }}><LogOut size={15} /> Log out</button>
      </header>
      <nav className="seller-tabs">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={15} /> {label}</button>
        ))}
      </nav>
      <main className="seller-main">
        {tab === "dashboard" && <DashboardTab profile={profile} />}
        {tab === "add" && <AddProductTab onCreated={refreshAll} />}
        {tab === "inventory" && <InventoryTab products={products} onAddVariant={addVariant} />}
        {tab === "orders" && <OrdersTab orders={orders} onMark={markOrder} />}
        {tab === "kyc" && <KycTab profile={profile} onRefresh={refreshAll} />}
      </main>
      {toast && <div className="toast" role="status"><Check size={16} /> {toast}</div>}
    </div>
  );
}
