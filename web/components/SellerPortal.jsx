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
import Link from "next/link";

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

const SPEC_TEMPLATES = {
  "Kurti, Saree & Lehenga": [["fabric", "Fabric composition", "text", "%", "fabric"], ["gsm", "Fabric weight", "number", "GSM", "fabric"], ["color_hex", "Color hex", "text", "", "color"]],
  "Women Western": [["fabric", "Fabric composition", "text", "%", "fabric"], ["fit", "Fit", "text", "", "construction"], ["color_hex", "Color hex", "text", "", "color"]],
  Lingerie: [["fabric", "Fabric composition", "text", "%", "fabric"], ["support_level", "Support level", "text", "", "performance"]],
  Men: [["fabric", "Fabric composition", "text", "%", "fabric"], ["gsm", "Fabric weight", "number", "GSM", "fabric"], ["fit", "Fit", "text", "", "construction"]],
  "Kids & Toys": [["material", "Material", "text", "", "construction"], ["recommended_age", "Recommended age", "text", "", "safety"]],
  "Home & Kitchen": [["material", "Material", "text", "", "construction"], ["length_cm", "Length", "measurement", "cm", "dimensions"], ["width_cm", "Width", "measurement", "cm", "dimensions"]],
  "Beauty & Health": [["net_quantity", "Net quantity", "number", "ml", "quantity"], ["skin_type", "Suitable skin type", "text", "", "performance"]],
  "Jewellery & Accessories": [["base_metal", "Base metal", "text", "", "construction"], ["plating", "Plating", "text", "", "construction"], ["stone_type", "Stone type", "text", "", "construction"]],
  "Bags & Footwear": [["material", "Material", "text", "", "construction"], ["capacity_l", "Capacity", "number", "L", "dimensions"], ["sole_material", "Sole material", "text", "", "construction"]],
};

function specificationTemplate(category) {
  return (SPEC_TEMPLATES[category] || [["material", "Material", "text", "", "general"]]).map(([key, label, value_type, unit, comparison_group]) => ({ key, label, value: "", value_type, unit, comparison_group }));
}

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
    <div className="seller-auth-page"><header className="portal-public-header"><Link className="logo" href="/"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></Link><nav><Link href="/">Home</Link><Link href="/#products">Shop</Link><span>Seller Portal</span></nav></header><main className="seller-auth-shell">
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
    </main><footer className="portal-public-footer"><strong>Kavach Saathi</strong><span>Protected commerce for buyers and sellers</span><Link href="/">Return to storefront</Link></footer></div>
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
  const [form, setForm] = useState({ title: "", brand: "", category: CATEGORIES[0], price: "", original_price: "", description: "", stock_qty: "" });
  const [specifications, setSpecifications] = useState(() => specificationTemplate(CATEGORIES[0]));
  const [sizes, setSizes] = useState([]);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function updateSpec(index, field, value) {
    setSpecifications((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item));
  }

  function parseDimensions(value) {
    return Object.fromEntries(value.split(",").map((part) => part.split(":").map((item) => item.trim())).filter((pair) => pair.length === 2 && pair[0] && !Number.isNaN(Number(pair[1]))).map(([key, amount]) => [key.toLowerCase().replace(/\s+/g, "_"), Number(amount)]));
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

      const submittedSpecs = specifications.filter((item) => item.key && item.label && item.value !== "").map((item) => ({
        ...item,
        value: ["number", "percentage", "measurement"].includes(item.value_type) ? Number(item.value) : item.value,
        unit: item.unit || null,
        comparison_group: item.comparison_group || "general",
        comparable: true,
      }));
      if (!submittedSpecs.length) throw new Error("Add at least one product-specific specification");
      const submittedSizes = sizes.filter((row) => row.size).map((row) => ({
        size: row.size, dimensions_cm: parseDimensions(row.dimensions), stock_qty: Number(row.stock_qty || 0),
      }));
      const sellerSpecs = Object.fromEntries(submittedSpecs.map((item) => [item.key, item.value]));
      const product = await post("/seller/products", {
        title: form.title,
        brand: form.brand || null,
        category: form.category,
        description: form.description,
        price: Number(form.price),
        original_price: Number(form.original_price),
        image_keys: [presign.object_key],
        stock_qty: Number(form.stock_qty || 0),
        specifications: submittedSpecs,
        size_chart: submittedSizes,
      });

      setProgress("Agent 1 (SAM 2.0 + Nano Banana 2 / Stable Diffusion) and Agent 2 (Claude OCR + CLIP/ResNet-50) are verifying this listing — image generation can take several minutes on CPU.");
      const analysis = await postAndPoll(
        "/listings/analyze",
        { seller_id: product.seller_id, product_id: product.id, image_keys: [presign.object_key], seller_specs: sellerSpecs },
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
        <label>Brand<input value={form.brand} onChange={(event) => update("brand", event.target.value)} /></label>
        <label>Category
          <select value={form.category} onChange={(event) => { update("category", event.target.value); setSpecifications(specificationTemplate(event.target.value)); }}>
            {CATEGORIES.map((category) => <option key={category} value={category}>{category}</option>)}
          </select>
        </label>
        <label>Description<input value={form.description} onChange={(event) => update("description", event.target.value)} /></label>
        <label>Price (₹)<input type="number" min="1" value={form.price} onChange={(event) => update("price", event.target.value)} required /></label>
        <label>Original price (₹)<input type="number" min="1" value={form.original_price} onChange={(event) => update("original_price", event.target.value)} required /></label>
        <label>Standard stock (used when there is no size chart)<input type="number" min="0" value={form.stock_qty} onChange={(event) => update("stock_qty", event.target.value)} /></label>
        <fieldset className="dynamic-specs"><legend>Product-specific specifications</legend><small>Add only fields that apply to this product. They are stored for grounded comparisons.</small>
          {specifications.map((item, index) => <div className="dynamic-spec-row" key={`${item.key}-${index}`}>
            <input placeholder="Key" value={item.key} onChange={(event) => updateSpec(index, "key", event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} required />
            <input placeholder="Display label" value={item.label} onChange={(event) => updateSpec(index, "label", event.target.value)} required />
            <input placeholder="Value" value={item.value} onChange={(event) => updateSpec(index, "value", event.target.value)} required />
            <select value={item.value_type} onChange={(event) => updateSpec(index, "value_type", event.target.value)}><option value="text">Text</option><option value="number">Number</option><option value="percentage">Percentage</option><option value="measurement">Measurement</option></select>
            <input placeholder="Unit" value={item.unit} onChange={(event) => updateSpec(index, "unit", event.target.value)} />
            <button type="button" onClick={() => setSpecifications((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
          </div>)}
          <button className="secondary-cta" type="button" onClick={() => setSpecifications((current) => [...current, { key: "", label: "", value: "", value_type: "text", unit: "", comparison_group: "general" }])}>Add specification</button>
        </fieldset>
        <fieldset className="dynamic-specs"><legend>Size chart (optional)</legend><small>Measurements are in cm. Use any applicable key:value dimensions.</small>
          {sizes.map((row, index) => <div className="dynamic-size-row" key={index}>
            <input placeholder="Size (e.g. M)" value={row.size} onChange={(event) => setSizes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, size: event.target.value } : item))} />
            <input placeholder="chest:91, waist:85, length:112" value={row.dimensions} onChange={(event) => setSizes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, dimensions: event.target.value } : item))} />
            <input type="number" min="0" placeholder="Stock" value={row.stock_qty} onChange={(event) => setSizes((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, stock_qty: event.target.value } : item))} />
            <button type="button" onClick={() => setSizes((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Remove</button>
          </div>)}
          <button className="secondary-cta" type="button" onClick={() => setSizes((current) => [...current, { size: "", dimensions: "", stock_qty: "" }])}>Add size</button>
        </fieldset>
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

function InventoryTab({ products, onAddVariant, busyAction }) {
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
            {!!product.specifications?.length && <p>{product.specifications.map((item) => `${item.label}: ${item.value}${item.unit ? ` ${item.unit}` : ""}`).join(" · ")}</p>}
            {!!Object.keys(product.size_chart || {}).length && <p>Size chart: {Object.entries(product.size_chart).map(([size, dimensions]) => `${size} (${Object.entries(dimensions).map(([key, value]) => `${key} ${value}cm`).join(", ")})`).join(" · ")}</p>}
            {product.stolen_photo_flag && <p className="warn-note">Flagged: possible copied catalogue photo</p>}
          </div>
          <div className="variant-list">
            {product.variants.map((variant) => <span key={variant.id} className="variant-chip">{variant.size}: {variant.stock_qty} units</span>)}
          </div>
          <form
            className="variant-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const form = variantForm[product.id] || {};
              if (!form.size || !form.stock_qty) return;
              await onAddVariant(product.id, { size: form.size, stock_qty: Number(form.stock_qty) });
            }}
          >
            <input placeholder="Size (e.g. M)" value={variantForm[product.id]?.size || ""} onChange={(event) => updateVariant(product.id, "size", event.target.value)} />
            <input placeholder="Stock" type="number" min="0" value={variantForm[product.id]?.stock_qty || ""} onChange={(event) => updateVariant(product.id, "stock_qty", event.target.value)} />
            <button type="submit" disabled={busyAction === `variant-${product.id}`}>{busyAction === `variant-${product.id}` ? <LoaderCircle className="spin" size={14} /> : <Boxes size={14} />} {busyAction === `variant-${product.id}` ? "Saving…" : "Add/update variant"}</button>
          </form>
        </article>
      ))}
    </div>
  );
}

function OrdersTab({ orders, onMark, busyAction }) {
  return (
    <div className="seller-panel">
      {!orders.length && <p className="empty-note">No orders yet for your listings.</p>}
      {orders.map((order) => (
        <article className="order-row" key={`${order.order_id}-${order.product_id}`}>
          <div><strong>{order.order_id}</strong><span className="status-pill">{order.status}</span></div>
          <p>{order.product_id} · size {order.size || "Standard"} · qty {order.qty} · ₹{order.price_at_purchase}</p>
          <div className="order-actions">
            <button type="button" disabled={busyAction === `order-${order.order_id}`} onClick={() => onMark(order.order_id, "PACKED")}>{busyAction === `order-${order.order_id}` ? <LoaderCircle className="spin" size={13} /> : <Package size={13} />} Mark packed</button>
            <button type="button" disabled={busyAction === `order-${order.order_id}`} onClick={() => onMark(order.order_id, "SHIPPED")}>{busyAction === `order-${order.order_id}` ? <LoaderCircle className="spin" size={13} /> : <ClipboardList size={13} />} Mark shipped</button>
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
  const [actionBusy, setActionBusy] = useState("");

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
    setActionBusy(`variant-${productId}`);
    try {
      await post(`/seller/products/${productId}/variants`, payload);
      await refreshAll();
      setToast("Variant saved");
    } catch (reason) {
      setToast(reason.message);
    } finally {
      setActionBusy("");
    }
  }

  async function markOrder(orderId, status) {
    setActionBusy(`order-${orderId}`);
    try {
      await request(`/seller/orders/${orderId}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      await refreshAll();
      setToast(`Order ${orderId} marked ${status.toLowerCase()}`);
    } catch (reason) {
      setToast(reason.message);
    } finally {
      setActionBusy("");
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
        {tab === "inventory" && <InventoryTab products={products} onAddVariant={addVariant} busyAction={actionBusy} />}
        {tab === "orders" && <OrdersTab orders={orders} onMark={markOrder} busyAction={actionBusy} />}
        {tab === "kyc" && <KycTab profile={profile} onRefresh={refreshAll} />}
      </main>
      {toast && <div className="toast" role="status" aria-live="polite"><Check size={16} /> {toast}</div>}
    </div>
  );
}
