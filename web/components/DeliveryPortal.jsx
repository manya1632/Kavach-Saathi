"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, FileImage, LoaderCircle, LogOut, MapPin, RotateCcw, ShieldCheck, Truck, Upload } from "lucide-react";

import { get, loadAuthSession, post } from "@/lib/api";

const TABS = [
  ["pending-deliveries", "Pending deliveries"],
  ["completed-deliveries", "Completed deliveries"],
  ["pending-returns", "Pending returns"],
  ["completed-returns", "Completed returns"],
];

async function uploadImage(file, kind) {
  const slot = await post("/uploads/presign", { filename: file.name, content_type: file.type, kind });
  const response = await fetch(slot.upload_url, { method: "PUT", headers: { "Content-Type": file.type }, body: file });
  if (!response.ok) throw new Error(`Image upload failed (${response.status})`);
  return slot.object_key;
}

export default function DeliveryPortal() {
  const router = useRouter();
  const [auth] = useState(() => loadAuthSession());
  const [activeTab, setActiveTab] = useState("pending-deliveries");
  const [deliveries, setDeliveries] = useState([]);
  const [returns, setReturns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [workflow, setWorkflow] = useState(null);
  const [frontImage, setFrontImage] = useState(null);
  const [backImage, setBackImage] = useState(null);
  const [otp, setOtp] = useState("");
  const [checks, setChecks] = useState({ matches_images: false, seal_and_tags_present: false, undamaged: false });
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [deliveryRows, returnRows] = await Promise.all([get("/delivery/deliveries"), get("/delivery/returns")]);
      setDeliveries(deliveryRows);
      setReturns(returnRows);
    } catch (reason) {
      setError(reason.message || "The delivery queue could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!auth || auth.user.role !== "delivery_boy") {
      router.replace("/");
      return;
    }
    Promise.resolve().then(refresh);
  }, [auth, router]);

  const rows = activeTab === "pending-deliveries" ? deliveries.filter((row) => row.queue_state === "pending")
    : activeTab === "completed-deliveries" ? deliveries.filter((row) => row.queue_state === "completed")
      : activeTab === "pending-returns" ? returns.filter((row) => row.queue_state === "pending")
        : returns.filter((row) => row.queue_state === "completed");

  async function beginOtp() {
    setBusy(true); setError("");
    try {
      const path = workflow.type === "delivery"
        ? `/delivery/deliveries/${workflow.order_id}/otp/send`
        : `/delivery/returns/${workflow.return_id}/otp/send`;
      await post(path, { idempotency_key: crypto.randomUUID() });
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  async function completeDelivery() {
    if (!frontImage || !backImage || !otp) return;
    setBusy(true); setError("");
    try {
      const [frontKey, backKey] = await Promise.all([uploadImage(frontImage, "delivery"), uploadImage(backImage, "delivery")]);
      await post(`/delivery/deliveries/${workflow.order_id}/evidence`, {
        front_image_key: frontKey,
        back_image_key: backKey,
        idempotency_key: crypto.randomUUID(),
      });
      await post(`/delivery/deliveries/${workflow.order_id}/complete`, { otp_code: otp, idempotency_key: crypto.randomUUID() });
      setWorkflow(null); setFrontImage(null); setBackImage(null); setOtp("");
      await refresh();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  async function completeReturn() {
    if (!otp || !Object.values(checks).every(Boolean)) return;
    setBusy(true); setError("");
    try {
      await post(`/delivery/returns/${workflow.return_id}/complete`, {
        otp_code: otp,
        inspection_checklist: checks,
        idempotency_key: crypto.randomUUID(),
      });
      setWorkflow(null); setOtp("");
      setChecks({ matches_images: false, seal_and_tags_present: false, undamaged: false });
      await refresh();
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  if (!auth || auth.user.role !== "delivery_boy") return <main className="delivery-loading"><LoaderCircle className="spin" /> Checking access…</main>;

  return (
    <main className="delivery-portal">
      <header className="delivery-header"><div><Truck /><span><strong>Kavach Saathi Delivery</strong><small>Shared operational queue · signed in as {auth.user.name}</small></span></div><button type="button" onClick={() => { localStorage.removeItem("kavach.auth.v1"); router.push("/"); }}><LogOut size={16} /> Logout</button></header>
      <nav className="delivery-tabs" aria-label="Delivery queue sections">{TABS.map(([id, label]) => <button type="button" className={activeTab === id ? "active" : ""} onClick={() => setActiveTab(id)} key={id}>{label}</button>)}</nav>
      {error && <p className="delivery-error">{error}</p>}
      {loading ? <div className="delivery-loading"><LoaderCircle className="spin" /> Loading queue…</div> : (
        <section className="delivery-grid">
          {!rows.length && <div className="delivery-empty"><CheckCircle2 /><p>No records in this queue.</p></div>}
          {rows.map((row) => {
            const isReturn = Boolean(row.return_id);
            const key = row.return_id || row.order_id;
            return <article className="delivery-card" key={key}>
              <div className="delivery-card-title"><span>{isReturn ? <RotateCcw /> : <Truck />}</span><div><small>{isReturn ? "RETURN" : "ORDER"}</small><strong>{key}</strong></div><b>{row.status.replaceAll("_", " ")}</b></div>
              <dl><div><dt>Recipient</dt><dd>{row.customer_name}</dd></div><div><dt>Phone</dt><dd>{row.phone}</dd></div><div><dt>DIGIPIN</dt><dd>{row.address?.digipin || "—"}</dd></div>{!isReturn && <><div><dt>Payment</dt><dd>{row.payment_mode?.toUpperCase()} · {row.payment_status}</dd></div><div><dt>Promised date</dt><dd>{row.promised_delivery_date || "Buyer confirmation pending"}</dd></div></>}</dl>
              <p>{row.address?.raw_text || [row.address?.city, row.address?.state, row.address?.postal_pin].filter(Boolean).join(", ")}</p>
              <div className="delivery-actions"><a href={row.gmaps_directions_url} target="_blank" rel="noreferrer"><MapPin size={15} /> Locate buyer</a>{row.queue_state === "pending" && <button type="button" onClick={() => setWorkflow({ type: isReturn ? "return" : "delivery", ...row })}>{isReturn ? "Inspect return" : "Deliver order"}</button>}</div>
            </article>;
          })}
        </section>
      )}

      {workflow && <div className="delivery-modal-layer"><section className="delivery-modal" role="dialog" aria-modal="true"><header><div><ShieldCheck /><strong>{workflow.type === "delivery" ? "Delivery verification" : "Return inspection"}</strong></div><button type="button" onClick={() => setWorkflow(null)}>×</button></header>
        {workflow.type === "delivery" ? <><p>Upload clear front and back images for every returnable item before requesting the buyer’s WhatsApp OTP.</p><label><FileImage /> Front image<input type="file" accept="image/*" capture="environment" onChange={(event) => setFrontImage(event.target.files?.[0] || null)} /></label><label><FileImage /> Back image<input type="file" accept="image/*" capture="environment" onChange={(event) => setBackImage(event.target.files?.[0] || null)} /></label></> : <><p>Compare the delivery evidence and buyer-submitted front/back images before approving pickup.</p>{[["matches_images", "Product matches both evidence sets"], ["seal_and_tags_present", "Required seal and price tags are present"], ["undamaged", "Product is undamaged"]].map(([name, label]) => <label className="inspection-check" key={name}><input type="checkbox" checked={checks[name]} onChange={(event) => setChecks((current) => ({ ...current, [name]: event.target.checked }))} /> {label}</label>)}</>}
        <button type="button" className="secondary-cta" onClick={beginOtp} disabled={busy}><Upload size={15} /> Send WhatsApp OTP</button><input value={otp} onChange={(event) => setOtp(event.target.value)} inputMode="numeric" placeholder="Buyer-provided OTP" aria-label="Buyer OTP" />
        <button type="button" className="primary-cta" onClick={workflow.type === "delivery" ? completeDelivery : completeReturn} disabled={busy || !otp || (workflow.type === "delivery" ? !frontImage || !backImage : !Object.values(checks).every(Boolean))}>{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />} {workflow.type === "delivery" ? "Complete delivery" : "Approve return"}</button>
      </section></div>}
    </main>
  );
}
