"use client";

import {
  AlertTriangle,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import { get, loadAuthSession, login, logout, patchJson, post, saveAuthSession } from "@/lib/api";

function AdminAuth({ onAuthenticated }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await login(email, password);
      if (session.user.role !== "admin") {
        saveAuthSession(null);
        throw new Error("This account is not an admin account.");
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
        <div className="seller-brand"><ShieldAlert size={22} /><div><strong>Kavach Saathi</strong><small>Admin Console</small></div></div>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>Admin email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {error && <p className="auth-error">{error}</p>}
          <button className="primary-cta wide" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : null} Log in</button>
        </form>
      </div>
    </div>
  );
}

function DashboardTab({ analytics, onRecompute, busy }) {
  if (!analytics) return null;
  const confidenceEntries = Object.entries(analytics.avg_confidence_by_agent || {});
  return (
    <div className="seller-panel">
      <div className="seller-stat-grid">
        <div><strong>{analytics.total_orders}</strong><span>Orders</span></div>
        <div><strong>₹{analytics.total_revenue}</strong><span>Revenue</span></div>
        <div><strong>{analytics.total_reviews}</strong><span>Reviews</span></div>
        <div><strong>{analytics.hidden_reviews}</strong><span>Hidden reviews</span></div>
        <div><strong>{analytics.total_returns}</strong><span>Returns</span></div>
        <div><strong>{analytics.manual_review_returns}</strong><span>Manual review</span></div>
      </div>
      <h4>Average agent confidence</h4>
      {!confidenceEntries.length && <p className="empty-note">No agent_logs rows yet.</p>}
      {confidenceEntries.map(([agent, value]) => (
        <div className="inventory-row" key={agent}>
          <strong>{agent}</strong><span className="status-pill">{value}</span>
        </div>
      ))}
      <button className="secondary-cta wide" type="button" onClick={onRecompute} disabled={busy}>
        {busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCcw size={16} />} Recompute all trust scores
      </button>
    </div>
  );
}

function InspectionQueueTab({ queue, onResolve, resolving }) {
  return (
    <div className="seller-panel">
      {!queue.length && <p className="empty-note">No returns are waiting on manual inspection right now.</p>}
      {queue.map((item) => (
        <article className="inventory-row" key={item.return_id}>
          <div>
            <strong>{item.return_id}</strong>
            <span className="status-pill">confidence {item.confidence_score}</span>
          </div>
          <p>Order {item.order_id} · buyer {item.buyer_id}</p>
          <div className="order-actions">
            <button type="button" disabled={resolving === item.return_id} onClick={() => onResolve(item.return_id, "approve")}>{resolving === item.return_id ? <LoaderCircle className="spin" size={13} /> : null} Approve return</button>
            <button type="button" disabled={resolving === item.return_id} onClick={() => onResolve(item.return_id, "reject")}>{resolving === item.return_id ? <LoaderCircle className="spin" size={13} /> : null} Reject return</button>
          </div>
        </article>
      ))}
    </div>
  );
}

function FraudTab({ fraud }) {
  if (!fraud) return null;
  return (
    <div className="seller-panel">
      <h4>Stolen-photo products</h4>
      {!fraud.stolen_photo_products.length && <p className="empty-note">None flagged.</p>}
      {fraud.stolen_photo_products.map((p) => (
        <div className="inventory-row" key={p.product_id}><strong>{p.title}</strong><p className="warn-note">{p.product_id} · seller {p.seller_id}</p></div>
      ))}
      <h4>Sellers with fraud flags</h4>
      {!fraud.flagged_sellers.length && <p className="empty-note">None flagged.</p>}
      {fraud.flagged_sellers.map((s) => (
        <div className="inventory-row" key={s.seller_id}><strong>{s.seller_id}</strong><p className="warn-note">{s.fraud_flags} flags · RTO rate {s.rto_rate}%</p></div>
      ))}
      <h4>Buyers with fraud flags</h4>
      {!fraud.flagged_buyers.length && <p className="empty-note">None flagged.</p>}
      {fraud.flagged_buyers.map((b) => (
        <div className="inventory-row" key={b.buyer_id}><strong>{b.buyer_id}</strong><p className="warn-note">{b.fraud_flags} flags · return rate {b.return_rate}</p></div>
      ))}
    </div>
  );
}

function TrustOverrideTab({ onOverride, toast }) {
  const [sellerId, setSellerId] = useState("");
  const [trustScore, setTrustScore] = useState("");
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await onOverride(sellerId, {
        trust_score: trustScore === "" ? null : Number(trustScore),
        verified,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="seller-panel">
      <form className="auth-form" onSubmit={handleSubmit}>
        <label>Seller ID<input value={sellerId} onChange={(event) => setSellerId(event.target.value)} placeholder="S-001" required /></label>
        <label>Trust score override (0-100)<input type="number" min="0" max="100" value={trustScore} onChange={(event) => setTrustScore(event.target.value)} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={verified} onChange={(event) => setVerified(event.target.checked)} /> Mark verified</label>
        <button className="primary-cta wide" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Gauge size={16} />} Apply override</button>
      </form>
      {toast && <p className="auth-error">{toast}</p>}
    </div>
  );
}

export default function AdminConsole() {
  const [auth, setAuth] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("dashboard");
  const [analytics, setAnalytics] = useState(null);
  const [queue, setQueue] = useState([]);
  const [fraud, setFraud] = useState(null);
  const [toast, setToast] = useState("");
  const [recomputing, setRecomputing] = useState(false);
  const [resolving, setResolving] = useState("");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuth(loadAuthSession());
    setReady(true);
  }, []);

  async function refreshAll() {
    const [analyticsData, queueData, fraudData] = await Promise.all([
      get("/admin/analytics"),
      get("/admin/inspection-queue"),
      get("/admin/fraud-cases"),
    ]);
    setAnalytics(analyticsData);
    setQueue(queueData);
    setFraud(fraudData);
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async data fetch on mount/auth change
    if (auth?.user?.role === "admin") refreshAll().catch((reason) => setToast(reason.message));
  }, [auth]);

  useEffect(() => {
    if (!toast) return undefined;
    const id = window.setTimeout(() => setToast(""), 3000);
    return () => window.clearTimeout(id);
  }, [toast]);

  if (!ready) return null;
  if (!auth?.user || auth.user.role !== "admin") {
    return <AdminAuth onAuthenticated={setAuth} />;
  }

  async function resolveReturn(returnId, decision) {
    setResolving(returnId);
    try {
      await post(`/admin/returns/${returnId}/resolve`, { decision });
      await refreshAll();
      setToast(`Return ${returnId} ${decision}d`);
    } catch (reason) {
      setToast(reason.message);
    } finally {
      setResolving("");
    }
  }

  async function overrideTrustScore(sellerId, payload) {
    try {
      await patchJson(`/admin/sellers/${sellerId}/trust-score`, payload);
      setToast(`Trust score for ${sellerId} updated`);
    } catch (reason) {
      setToast(reason.message);
    }
  }

  async function recomputeAll() {
    setRecomputing(true);
    try {
      const result = await post("/admin/trust-scores/recompute", {});
      setToast(`Recomputed ${result.sellers_updated} sellers, ${result.buyers_updated} buyers`);
      await refreshAll();
    } catch (reason) {
      setToast(reason.message);
    } finally {
      setRecomputing(false);
    }
  }

  const tabs = [
    { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { key: "inspection", label: "Inspection Queue", icon: AlertTriangle },
    { key: "fraud", label: "Fraud Cases", icon: ShieldAlert },
    { key: "trust", label: "Trust Override", icon: Gauge },
  ];

  return (
    <div className="seller-portal">
      <header className="seller-header">
        <div className="seller-brand"><ShieldAlert size={20} /><div><strong>Kavach Saathi</strong><small>Admin Console</small></div></div>
        <button type="button" className="logout-link" onClick={() => { logout(); setAuth(null); }}><LogOut size={15} /> Log out</button>
      </header>
      <nav className="seller-tabs">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={15} /> {label}</button>
        ))}
      </nav>
      <main className="seller-main">
        {tab === "dashboard" && <DashboardTab analytics={analytics} onRecompute={recomputeAll} busy={recomputing} />}
        {tab === "inspection" && <InspectionQueueTab queue={queue} onResolve={resolveReturn} resolving={resolving} />}
        {tab === "fraud" && <FraudTab fraud={fraud} />}
        {tab === "trust" && <TrustOverrideTab onOverride={overrideTrustScore} toast={toast} />}
      </main>
      {toast && <div className="toast" role="status" aria-live="polite"><ShieldCheck size={16} /> {toast}</div>}
    </div>
  );
}
