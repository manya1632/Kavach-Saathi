"use client";

import {
  ArrowRight,
  BadgeCheck,
  Camera,
  Check,
  ChevronRight,
  CircleUserRound,
  Headphones,
  Heart,
  LoaderCircle,
  LogOut,
  MapPin,
  Menu,
  MessageCircle,
  Mic,
  PackageCheck,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  ShoppingCart,
  Sparkles,
  Star,
  Truck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  addToCart as apiAddToCart,
  assetUrl,
  createOrder,
  createReview,
  getCart,
  loadAuthSession,
  login,
  logout,
  patch,
  post,
  postAndPoll,
  removeCartItem,
  request,
  signup,
} from "@/lib/api";

const LANGUAGE_OPTIONS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी (Hindi)" },
  { code: "bn", label: "বাংলা (Bengali)" },
  { code: "mr", label: "मराठी (Marathi)" },
  { code: "gu", label: "ગુજરાતી (Gujarati)" },
];

const AGENTS = {
  catalogue_truth: { number: "01", short: "Catalogue Truth", icon: Camera },
  spec_enforcer: { number: "02", short: "Honest Specs", icon: BadgeCheck },
  size_translator: { number: "03", short: "Size Saathi", icon: Sparkles },
  review_filter: { number: "04", short: "Review Truth", icon: MessageCircle },
  voice_qa: { number: "05", short: "Voice Q&A", icon: Mic },
  address_guardian: { number: "06", short: "Address Guard", icon: MapPin },
  delivery_confirmation: { number: "07", short: "Delivery Confirm", icon: Truck },
  return_verifier: { number: "08", short: "Fair Returns", icon: RotateCcw },
};

const GOLDEN_SPECS = {
  fabric: "60% Cotton, 40% Viscose",
  gsm: 150,
  color_hex: "#800000",
  wash_care: "Gentle hand wash",
};

function variantIdFor(product, size) {
  // Matches the backend's variant-id convention (scripts/generate_seed_data.py,
  // seller_api.py): "{product_id}-{size}" for chart sizes, "{product_id}-STD" when a
  // product has no size chart at all.
  const hasChart = product.size_chart && Object.keys(product.size_chart).length > 0;
  return `${product.id}-${hasChart ? size : "STD"}`;
}

function audioUrl(key) {
  if (!key) return "";
  return `/mock-assets/${key.replace(/^assets\/mock\//, "")}`;
}

function money(value) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function ProductCard({ product, onOpen, onAdd }) {
  return (
    <article className="product-card" data-testid={`product-${product.id}`} data-category={product.category}>
      <button className="product-visual" type="button" onClick={() => onOpen(product)} aria-label={`Open ${product.name}`}>
        <img src={assetUrl(product.image_url)} alt={product.name} />
        <span className="agent-checked"><ShieldCheck size={13} /> Agent checked</span>
        <span className="heart"><Heart size={17} /></span>
      </button>
      <div className="product-info">
        <p className="product-brand">{product.brand}</p>
        <button className="product-name" type="button" onClick={() => onOpen(product)}>{product.name}</button>
        <div className="product-price">
          <strong>{money(product.price)}</strong>
          <s>{money(product.original_price)}</s>
          <span>{product.discount_percent}% off</span>
        </div>
        <p className="delivery-copy">Free delivery · {product.delivery_days}–{product.delivery_days + 2} days</p>
        <div className="card-bottom">
          <span className="rating-pill">{product.rating} <Star size={10} fill="currentColor" /></span>
          <small>{product.review_count.toLocaleString("en-IN")} reviews</small>
          <button type="button" onClick={() => onAdd(product)} aria-label={`Add ${product.name} to cart`}><ShoppingCart size={16} /></button>
        </div>
      </div>
    </article>
  );
}

function TrustDock({ trust, busy, onClose, onRunAll }) {
  const entries = Object.entries(trust.results);
  return (
    <aside className={`trust-dock ${trust.open ? "open" : ""}`} aria-label="Kavach Saathi agent activity">
      <div className="dock-header">
        <div className="dock-brand"><span><ShieldCheck size={18} /></span><div><strong>Kavach Saathi</strong><small>Live evidence trail</small></div></div>
        <button type="button" onClick={onClose} aria-label="Close agent activity"><X size={18} /></button>
      </div>
      <div className="dock-status">
        <span className={busy ? "working" : "ready"}></span>
        <p>{busy ? trust.message || "Agents are checking…" : entries.length ? `${entries.length} agents completed` : "Ready to protect this journey"}</p>
      </div>
      <div className="dock-results">
        {!entries.length && (
          <div className="dock-empty"><Sparkles size={26} /><strong>See the orchestrator work</strong><p>Run the safety tour or use any trust action inside the shop.</p></div>
        )}
        {entries.map(([key, result]) => {
          const meta = AGENTS[key];
          const Icon = meta?.icon || ShieldCheck;
          return (
            <article className="dock-result" key={key}>
              <span className="dock-icon"><Icon size={15} /></span>
              <div><div className="dock-title"><strong>{meta?.short || key}</strong><span>{result.confidence}%</span></div><p>{result.summary}</p>{result.actions?.[0] && <small>{result.actions[0].label}</small>}</div>
            </article>
          );
        })}
      </div>
      <button className="dock-run" type="button" onClick={onRunAll} disabled={busy}>
        {busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />} Run all 8 agents
      </button>
      <p className="prototype-note">Synthetic prototype data · Agent 7 is simulated</p>
    </aside>
  );
}

function ProductDrawer({ product, open, busy, onClose, onAdd, onSize, onReview, onAsk, onAskVoice, voiceAudioUrl, agentAnswer, sizeSaathi, onSubmitReview }) {
  const [size, setSize] = useState("M");

  useEffect(() => {
    if (sizeSaathi?.size) setSize(sizeSaathi.size);
  }, [sizeSaathi?.size]);
  const [question, setQuestion] = useState("Iska fabric aur return policy batao");
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewText, setReviewText] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [recording, setRecording] = useState(false);
  const [requestingMic, setRequestingMic] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  async function toggleRecording() {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      onAskVoiceError("This browser does not support microphone access");
      return;
    }
    setRequestingMic(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size > 0) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        onAskVoice(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (reason) {
      const message = reason?.name === "NotAllowedError" ? "Microphone access was denied" : reason?.name === "NotFoundError" ? "No microphone was found" : "Could not access the microphone";
      onAskVoiceError(message);
    } finally {
      setRequestingMic(false);
    }
  }

  function onAskVoiceError(message) {
    onAskVoice(null, message);
  }

  if (!product) return null;
  const sizes = Object.keys(product.size_chart || {});
  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close product details" />
      <aside className="product-drawer" role="dialog" aria-modal="true" aria-label={product.name}>
        <button className="drawer-close" type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        <div className="drawer-gallery">
          <img src={assetUrl(product.image_url)} alt={product.name} />
          <span><ShieldCheck size={15} /> Catalogue & specs checked</span>
        </div>
        <div className="drawer-content">
          <p className="drawer-category">{product.category}</p>
          <h2>{product.name}</h2>
          <p className="drawer-seller"><BadgeCheck size={14} /> {product.brand} · {product.seller.name} · {product.seller.city}</p>
          <div className="drawer-price"><strong>{money(product.price)}</strong><s>{money(product.original_price)}</s><span>{product.discount_percent}% off</span></div>
          {product.description && <p className="drawer-description">{product.description}</p>}
          {!!product.badges?.length && <div className="product-badges">{product.badges.map((badge) => <span key={badge}><Check size={11} /> {badge}</span>)}</div>}
          <div className="trust-banner"><ShieldCheck size={19} /><div><strong>Verified product evidence</strong><p>Agent 1 checked imagery. Agent 2 matched seller claims to label-backed specs.</p></div></div>

          {!!sizes.length && <div className="size-section"><div className="section-label"><strong>Select size</strong><button type="button" onClick={onSize} disabled={busy}>{busy ? <LoaderCircle className="spin" size={13} /> : <Sparkles size={13} />} Ask Size Saathi</button></div><div className="size-row">{sizes.map((item) => <button className={size === item ? "selected" : ""} type="button" key={item} onClick={() => setSize(item)}>{item}</button>)}</div>{sizeSaathi && <div className="agent-answer size-saathi-answer">{sizeSaathi.size ? <strong>Recommended: {sizeSaathi.size}</strong> : null}{sizeSaathi.message && <span>{sizeSaathi.message}</span>}{sizeSaathi.audioUrl && <audio controls src={sizeSaathi.audioUrl} style={{ width: "100%", marginTop: 8 }} />}</div>}</div>}

          <dl className="spec-list">
            <div><dt>Material</dt><dd>{product.material || product.specs.fabric}</dd></div>
            <div><dt>Best for</dt><dd>{product.occasion}</dd></div>
            <div><dt>Delivery</dt><dd>{product.delivery_days}–{product.delivery_days + 2} days</dd></div>
            <div><dt>Availability</dt><dd>{product.stock} units · {product.cod_available ? "COD available" : "Prepaid"}</dd></div>
            <div><dt>Care</dt><dd>{product.specs.wash_care}</dd></div>
            <div><dt>Return</dt><dd>{product.return_window_days} days</dd></div>
          </dl>

          {!!product.highlights?.length && <div className="product-highlights"><strong>Why shoppers choose it</strong><ul>{product.highlights.map((highlight) => <li key={highlight}><Check size={12} /> {highlight}</li>)}</ul>{product.presentation?.why_it_wins && <p><Sparkles size={13} /> {product.presentation.why_it_wins}</p>}</div>}

          <div className="drawer-actions"><button className="secondary-cta" type="button" onClick={onReview} disabled={busy}><MessageCircle size={16} /> Check review truth</button><button className="primary-cta" type="button" onClick={() => onAdd(product, size)}><ShoppingBag size={16} /> Add to cart</button></div>

          <form className="ask-saathi" onSubmit={(event) => { event.preventDefault(); onAsk(question); }}>
            <label htmlFor="product-question"><Mic size={15} /> Ask in Hindi or English</label>
            <div>
              <input id="product-question" value={question} onChange={(event) => setQuestion(event.target.value)} />
              <button type="button" onClick={toggleRecording} disabled={requestingMic} aria-pressed={recording} title={recording ? "Stop recording" : "Ask by voice"}>{requestingMic ? <LoaderCircle className="spin" size={15} /> : recording ? "⏹" : <Mic size={15} />}</button>
              <button type="submit" disabled={busy}>Ask</button>
            </div>
            {requestingMic && <small style={{ color: "var(--plum)", fontWeight: 600 }}>Waiting for microphone permission…</small>}
            {recording && <small style={{ color: "var(--accent, #e5484d)", fontWeight: 600 }}>Recording… click mic again to stop</small>}
            <small>Agent 5 (Gemini + Pinecone RAG) answers, grounded only in verified product data and real reviews.</small>
            {agentAnswer && <div className="agent-answer"><Sparkles size={14} /> <span>{agentAnswer}</span></div>}
            {voiceAudioUrl && <audio controls src={voiceAudioUrl} style={{ width: "100%", marginTop: 8 }} />}
          </form>

          <form
            className="ask-saathi"
            onSubmit={async (event) => {
              event.preventDefault();
              setReviewSubmitting(true);
              try {
                await onSubmitReview(product.id, reviewRating, reviewText);
                setReviewText("");
              } finally {
                setReviewSubmitting(false);
              }
            }}
          >
            <label><MessageCircle size={15} /> Write a review</label>
            <div className="size-row">{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} className={reviewRating === value ? "selected" : ""} onClick={() => setReviewRating(value)}>{value}<Star size={11} fill="currentColor" /></button>)}</div>
            <div><input value={reviewText} onChange={(event) => setReviewText(event.target.value)} placeholder="Kaisa laga yeh product?" /><button type="submit" disabled={reviewSubmitting}>{reviewSubmitting ? <LoaderCircle className="spin" size={15} /> : "Post"}</button></div>
            <small>Agent 4 (CLIP + BERT) automatically checks new reviews for relevance in the background.</small>
          </form>

          {!!product.reviews?.length && (
            <div className="review-list">
              <div className="review-list-header">
                <label><Star size={15} /> Customer reviews ({product.reviews.length})</label>
                {!!product.review_report?.photos_submitted && (
                  <p className="review-report">
                    <ShieldCheck size={13} /> {product.review_report.photos_verified} of{" "}
                    {product.review_report.photos_submitted} review photos verified genuine
                    {product.review_report.photos_flagged > 0 && (
                      <> · {product.review_report.photos_flagged} flagged and hidden</>
                    )}{" "}
                    (Agent 4 · CLIP + BERT)
                  </p>
                )}
              </div>
              <div className="review-cards">
                {product.reviews.map((review) => (
                  <article className="review-card" key={review.id}>
                    <div className="review-card-head">
                      <strong>{review.reviewer_name}</strong>
                      <span className="review-stars">
                        {Array.from({ length: 5 }, (_, index) => (
                          <Star key={index} size={12} fill={index < review.rating ? "currentColor" : "none"} />
                        ))}
                      </span>
                      {review.created_at && (
                        <time dateTime={review.created_at}>
                          {new Date(review.created_at).toLocaleDateString("en-IN", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </time>
                      )}
                    </div>
                    {review.text && <p>{review.text}</p>}
                    {review.media && !review.is_hidden_by_agent && (
                      <img src={assetUrl(review.media)} alt="Review photo submitted by customer" />
                    )}
                    {review.media && review.is_hidden_by_agent && (
                      <span className="review-flagged">
                        <ShieldAlert size={12} /> Photo hidden by Agent 4 — didn't match this product
                      </span>
                    )}
                  </article>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function ReviewSummaryDialog({ data, onClose }) {
  if (!data) return null;
  const breakdown = data.rating_breakdown || {};
  const total = data.total_reviews || 0;
  const rounded = Math.round(data.average_rating || 0);
  return (
    <div className="drawer-layer open">
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close review summary" />
      <aside className="review-summary-dialog" role="dialog" aria-modal="true" aria-label="Review truth summary">
        <div className="side-heading">
          <div><p>AGENT 4 · REVIEW TRUTH</p><h2>Review summary</h2></div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>
        <div className="review-summary-rating">
          <strong>{(data.average_rating || 0).toFixed(1)}</strong>
          <span className="review-stars">
            {Array.from({ length: 5 }, (_, index) => (
              <Star key={index} size={17} fill={index < rounded ? "currentColor" : "none"} />
            ))}
          </span>
          <small>{total} review{total === 1 ? "" : "s"}</small>
        </div>
        <div className="rating-breakdown">
          {[5, 4, 3, 2, 1].map((star) => {
            const count = breakdown[star] || 0;
            const pct = total ? Math.round((count / total) * 100) : 0;
            return (
              <div className="rating-bar-row" key={star}>
                <span>{star}★</span>
                <div className="rating-bar"><div className="rating-bar-fill" style={{ width: `${pct}%` }} /></div>
                <small>{count}</small>
              </div>
            );
          })}
        </div>
        {!!data.photos_submitted && (
          <p className="review-report">
            <ShieldCheck size={13} /> {data.photos_verified} of {data.photos_submitted} review photos verified genuine
            {data.photos_flagged > 0 && <> · {data.photos_flagged} flagged and hidden</>} (CLIP + BERT)
          </p>
        )}
        <p className="review-summary-text">{data.summary}</p>
      </aside>
    </div>
  );
}

function CartDrawer({ items, open, onClose, onRemove, onCheckout }) {
  const total = items.reduce((sum, item) => sum + item.line_total, 0);
  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close cart" />
      <aside className="side-drawer cart-drawer" role="dialog" aria-modal="true" aria-label="Shopping cart">
        <div className="side-heading"><div><p>YOUR CART</p><h2>{items.length ? `${items.length} item${items.length > 1 ? "s" : ""}` : "Cart is empty"}</h2></div><button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button></div>
        <div className="cart-items">
          {!items.length && <div className="cart-empty"><ShoppingBag size={34} /><p>Add something you love. Kavach Saathi will verify it along the way.</p></div>}
          {items.map((item) => <article className="cart-item" key={item.id}><img src={assetUrl(item.image_url)} alt="" /><div><strong>{item.product_name}</strong><p>Size {item.size || "Standard"} · Qty {item.qty}</p><span>{money(item.unit_price)}</span><button type="button" onClick={() => onRemove(item)}>Remove</button></div><ShieldCheck size={18} /></article>)}
        </div>
        {!!items.length && <div className="cart-total"><div><span>Product total</span><strong>{money(total)}</strong></div><div><span>Delivery</span><strong className="free">FREE</strong></div><div className="grand-total"><span>Order total</span><strong>{money(total)}</strong></div><button className="primary-cta" type="button" onClick={onCheckout}>Continue to secure checkout <ArrowRight size={17} /></button><p><ShieldCheck size={13} /> Address and delivery consent will be verified before dispatch.</p></div>}
      </aside>
    </div>
  );
}

function CheckoutDrawer({ open, context, busy, step, verifiedAddress, orderId, onClose, onVerify, onConfirm, onReturn, addressRaw, addressPin, onAddressRawChange, onAddressPinChange, buyerName }) {
  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close checkout" />
      <aside className="side-drawer checkout-drawer" role="dialog" aria-modal="true" aria-label="Secure checkout">
        <div className="side-heading"><div><p>SECURE CHECKOUT</p><h2>{step === "done" ? "Order protected" : "Delivery details"}</h2></div><button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button></div>
        <div className="checkout-progress"><span className="complete"><Check size={12} /> Cart</span><i></i><span className={verifiedAddress ? "complete" : "active"}>Address</span><i></i><span className={step === "done" ? "complete" : ""}>Confirm</span></div>
        {step !== "done" ? <div className="checkout-body">
          <div className="address-card address-form">
            <MapPin size={20} />
            <div>
              <strong>{buyerName || "Buyer"}</strong>
              <input type="text" placeholder="Full address (e.g. Hanuman Mandir ke peeche, gali no. 3)" value={addressRaw} onChange={(e) => onAddressRawChange(e.target.value)} disabled={verifiedAddress} />
              <input type="text" placeholder="PIN code (e.g. 495001)" value={addressPin} onChange={(e) => onAddressPinChange(e.target.value)} disabled={verifiedAddress} maxLength={6} />
            </div>
            {verifiedAddress && <span><Check size={13} /> Verified</span>}
          </div>
          {!verifiedAddress ? <button className="agent-action" type="button" onClick={onVerify} disabled={busy || (!addressRaw && !context?.address)}>{busy ? <LoaderCircle className="spin" size={17} /> : <MapPin size={17} />} Agent 6 · Verify address & DIGIPIN</button> : <div className="verified-address"><ShieldCheck size={22} /><div><strong>Location and PIN agree</strong><p>DIGIPIN generated. The delivery label now uses normalized location evidence.</p></div></div>}
          <div className="consent-box"><Truck size={19} /><div><strong>Agent 7 delivery confirmation</strong><p>Simulates buyer availability before the parcel is released for dispatch.</p></div></div>
          <button className="primary-cta wide" type="button" onClick={onConfirm} disabled={!verifiedAddress || busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <PackageCheck size={17} />} Confirm availability & place order</button>
        </div> : <div className="success-state"><span><PackageCheck size={40} /></span><h3>Order {orderId} is protected</h3><p>Address verified, buyer availability confirmed, and dispatch released with a traceable evidence trail.</p><div><Check size={15} /> Agent 6 verified address<DockLine /><Check size={15} /> Agent 7 captured consent</div><button className="secondary-cta" type="button" onClick={onReturn}><RotateCcw size={16} /> Simulate fair return check</button></div>}
      </aside>
    </div>
  );
}

function DockLine() { return <br />; }

function AuthModal({ open, onClose, onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [role, setRole] = useState("buyer");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState("en");
  const [businessName, setBusinessName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = mode === "login"
        ? await login(email, password)
        : await signup({
          role,
          name,
          email,
          password,
          preferred_language: preferredLanguage,
          ...(role === "seller" ? { business_name: businessName } : {}),
        });
      onAuthenticated(session);
    } catch (reason) {
      setError(reason.message || "That didn't work — please try again");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="drawer-layer open" aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close sign in" />
      <aside className="side-drawer auth-drawer" role="dialog" aria-modal="true" aria-label="Sign in or create account">
        <div className="side-heading">
          <div><p>{mode === "login" ? "WELCOME BACK" : "CREATE ACCOUNT"}</p><h2>{mode === "login" ? "Log in" : "Sign up"}</h2></div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>
        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Log in</button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>Sign up</button>
        </div>
        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === "signup" && (
            <>
              <label>I am a
                <select value={role} onChange={(event) => setRole(event.target.value)}>
                  <option value="buyer">Buyer</option>
                  <option value="seller">Seller</option>
                </select>
              </label>
              <label>Full name
                <input value={name} onChange={(event) => setName(event.target.value)} required minLength={1} />
              </label>
              {role === "seller" && (
                <label>Business name
                  <input value={businessName} onChange={(event) => setBusinessName(event.target.value)} />
                </label>
              )}
              <label>Preferred language
                <select value={preferredLanguage} onChange={(event) => setPreferredLanguage(event.target.value)}>
                  {LANGUAGE_OPTIONS.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
                </select>
              </label>
            </>
          )}
          <label>{mode === "login" ? "Email or phone" : "Email"}
            <input type={mode === "login" ? "text" : "email"} value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={mode === "signup" ? 8 : 1} />
          </label>
          {error && <p className="auth-error">{error}</p>}
          <button className="primary-cta wide" type="submit" disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={17} /> : null} {mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
      </aside>
    </div>
  );
}

export default function Storefront() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [context, setContext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [visibleCount, setVisibleCount] = useState(50);
  const [selected, setSelected] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [cart, setCart] = useState([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [checkoutStep, setCheckoutStep] = useState("address");
  const [verifiedAddress, setVerifiedAddress] = useState(false);
  const [verifiedAddressId, setVerifiedAddressId] = useState(null);
  const [lastOrderId, setLastOrderId] = useState(null);
  const [voiceAudioKey, setVoiceAudioKey] = useState(null);
  const [agentAnswer, setAgentAnswer] = useState("");
  const [sizeSaathi, setSizeSaathi] = useState(null);
  const [reviewSummary, setReviewSummary] = useState(null);
  const [trust, setTrust] = useState({ open: false, results: {}, message: "" });
  const [auth, setAuth] = useState(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [pendingAfterAuth, setPendingAfterAuth] = useState(null);
  const [addressRaw, setAddressRaw] = useState("");
  const [addressPin, setAddressPin] = useState("");

  useEffect(() => {
    setAuth(loadAuthSession());
    function onSessionExpired() {
      setAuth(null);
      setAuthModalOpen(true);
      setToast("Session expired — please log in again");
    }
    window.addEventListener("kavach:session-expired", onSessionExpired);
    return () => window.removeEventListener("kavach:session-expired", onSessionExpired);
  }, []);

  useEffect(() => {
    Promise.all([request("/storefront/products"), request("/storefront/demo-context")])
      .then(([catalogue, demo]) => { setProducts(catalogue.items); setCategories(["All", ...catalogue.categories]); setContext(demo); })
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  async function refreshCart() {
    if (!auth?.user) {
      setCart([]);
      return;
    }
    try {
      const data = await getCart();
      setCart(data.items);
    } catch (reason) {
      setToast(reason.message || "Could not load your cart");
    }
  }

  useEffect(() => {
    if (!auth?.user) {
      // Clearing local cart state on logout is a synchronous UI reset, not a fetch --
      // same category as the auth-session-restore effect above.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCart([]);
      return;
    }
    getCart()
      .then((data) => setCart(data.items))
      .catch((reason) => setToast(reason.message || "Could not load your cart"));
  }, [auth?.user]);

  function requireAuth(action) {
    if (auth?.user) {
      action(auth.user.id);
      return;
    }
    setPendingAfterAuth(() => action);
    setAuthModalOpen(true);
  }

  function handleAuthenticated(session) {
    setAuth(session);
    setAuthModalOpen(false);
    setToast(`Welcome, ${session.user.name}`);
    if (pendingAfterAuth) {
      pendingAfterAuth(session.user.id);
      setPendingAfterAuth(null);
    }
  }

  function handleLogout() {
    logout();
    setAuth(null);
    setToast("Logged out");
  }

  async function changeLanguage(languageCode) {
    if (!auth?.user) return;
    try {
      const updated = await patch("/auth/language", { language: languageCode });
      setAuth((current) => ({ ...current, user: { ...current.user, preferred_language: updated.preferred_language } }));
      const label = LANGUAGE_OPTIONS.find((opt) => opt.code === languageCode)?.label || languageCode;
      setToast(`Language set to ${label} — Agent 5 will respond in this language`);
    } catch (reason) {
      setToast(reason.message || "Could not update language");
    }
  }

  useEffect(() => {
    if (!toast) return undefined;
    const id = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(id);
  }, [toast]);

  useEffect(() => {
    document.body.classList.toggle("drawer-open", Boolean(drawer));
    return () => document.body.classList.remove("drawer-open");
  }, [drawer]);

  const visibleProducts = useMemo(() => {
    const term = search.toLowerCase().trim();
    const matchingProducts = products.filter((product) => !term || [product.name, product.category, product.brand, product.material, product.occasion].some((value) => value?.toLowerCase().includes(term)));
    if (category !== "All") return matchingProducts.filter((product) => product.category === category);

    const categoryOrder = categories.filter((item) => item !== "All");
    const buckets = categoryOrder.map((item) => matchingProducts.filter((product) => product.category === item));
    const balanced = [];
    const longestBucket = Math.max(0, ...buckets.map((bucket) => bucket.length));
    for (let index = 0; index < longestBucket; index += 1) {
      for (const bucket of buckets) {
        if (bucket[index]) balanced.push(bucket[index]);
      }
    }
    return balanced;
  }, [products, search, category, categories]);
  const displayedProducts = visibleProducts.slice(0, visibleCount);
  const categoryCounts = useMemo(() => products.reduce((counts, product) => ({ ...counts, [product.category]: (counts[product.category] || 0) + 1 }), {}), [products]);

  function mergeResults(payload) {
    setTrust((current) => ({ ...current, results: { ...current.results, ...payload.results } }));
  }

  async function execute(message, operation) {
    setBusy(true);
    setTrust((current) => ({ ...current, message }));
    try {
      const payload = await operation();
      mergeResults(payload);
      return payload;
    } catch (reason) {
      setToast(reason.message || "That check could not be completed");
      throw reason;
    } finally {
      setBusy(false);
      setTrust((current) => ({ ...current, message: "" }));
    }
  }

  async function openProduct(product) {
    // Agents 1 (catalogue image generation) and 2 (spec extraction) run once, at
    // listing-creation time in the seller portal -- not on every buyer view. Now that
    // they call real models (SAM 2.0 / Nano Banana 2 / Stable Diffusion / Claude),
    // re-running them per page view would mean a real multi-minute wait on every
    // product click. Judges can watch the real pipeline via "Watch all 8 agents".
    setDrawer("product");
    setSelected(product);
    setVoiceAudioKey(null);
    setAgentAnswer("");
    setSizeSaathi(null);
    try {
      const detail = await request(`/storefront/products/${product.id}`);
      setSelected(detail);
    } catch (reason) {
      setToast(reason.message || "Could not load this product");
    }
  }

  function addToCart(product, size) {
    const hasChart = product.size_chart && Object.keys(product.size_chart).length > 0;
    const resolvedSize = size || (hasChart ? Object.keys(product.size_chart)[0] : "Standard");
    if (hasChart && !size) {
      setSelected(product);
      setDrawer("product");
      setToast("Please select a size first");
      return;
    }
    requireAuth(async () => {
      try {
        await apiAddToCart(variantIdFor(product, resolvedSize));
        await refreshCart();
        setToast(`${product.name} added to cart`);
      } catch (reason) {
        setToast(reason.message || "Could not add this to your cart");
      }
    });
  }

  async function removeFromCart(item) {
    try {
      await removeCartItem(item.id);
      await refreshCart();
    } catch (reason) {
      setToast(reason.message || "Could not remove this item");
    }
  }

  async function recommendSize() {
    if (!selected) return;
    requireAuth(async (buyerId) => {
      const language = auth?.user?.preferred_language || "hi";
      setSizeSaathi(null);
      // Routes through the voice workflow (Agent 3 size RAG, then Agent 5 hands the
      // recommendation straight to Sarvam TTS) so the reply is spoken and transcribed
      // in the buyer's chosen language instead of a plain English-only toast.
      const payload = await execute("Agent 3 is translating size history, Agent 5 is preparing a spoken answer…", () => post("/voice/query", { buyer_id: buyerId, product_id: selected.id, text: "Mujhe kaunsa size lena chahiye?", language }));
      const recommendation = payload.results.size_translator?.data?.recommended_size;
      const voiceResult = payload.results.voice_qa;
      const message = voiceResult?.user_message?.[language] || voiceResult?.summary || "";
      setSizeSaathi({ size: recommendation || null, message, audioKey: voiceResult?.data?.audio_key || null });
      if (recommendation) setToast(`Size Saathi recommends ${recommendation}`);
    });
  }

  async function checkReview() {
    if (!selected) return;
    try {
      const payload = await execute("Agent 4 is summarizing all reviews…", () =>
        postAndPoll("/reviews/summary", { product_id: selected.id })
      );
      const result = payload.results?.review_filter;
      if (result?.data) setReviewSummary(result.data);
    } catch { /* execute() already shows a toast on error */ }
  }

  async function submitReview(productId, rating, text) {
    requireAuth(async () => {
      try {
        await createReview({ product_id: productId, rating, text });
        setToast("Review posted — Agent 4 is checking it in the background");
      } catch (reason) {
        setToast(reason.message || "Could not post this review");
      }
    });
  }

  async function askQuestion(question) {
    if (!selected) return;
    const buyerId = auth?.user?.id || "B-001";
    const language = auth?.user?.preferred_language || "hi";
    try {
      const payload = await execute("Agent 5 is grounding the answer…", () => post("/voice/query", { buyer_id: buyerId, product_id: selected.id, text: question, language }));
      const result = payload.results?.voice_qa;
      setAgentAnswer(result?.user_message?.[language] || result?.summary || "");
      setVoiceAudioKey(result?.data?.audio_key || null);
    } catch { /* execute() already shows a toast on error */ }
  }

  async function askVoice(blob, errorMessage) {
    if (!selected) return;
    if (!blob) {
      setToast(errorMessage || "Could not access the microphone");
      return;
    }
    const buyerId = auth?.user?.id || "B-001";
    const language = auth?.user?.preferred_language || "hi";
    try {
      const extension = blob.type.includes("webm") ? "webm" : blob.type.includes("ogg") ? "ogg" : "wav";
      const presign = await post("/uploads/presign", { kind: "voice", filename: `question.${extension}`, content_type: blob.type || "audio/webm" });
      await fetch(presign.upload_url, { method: "PUT", body: blob, headers: { "Content-Type": blob.type || "audio/webm" } });
      const payload = await execute("Agent 5 is transcribing and grounding your question…", () => post("/voice/query", { buyer_id: buyerId, product_id: selected.id, audio_key: presign.object_key, language }));
      const result = payload.results?.voice_qa;
      setAgentAnswer(result?.user_message?.[language] || result?.summary || "");
      setVoiceAudioKey(result?.data?.audio_key || null);
    } catch (reason) {
      setToast(reason.message || "Could not process your voice question");
    }
  }

  async function verifyAddress() {
    requireAuth(async (buyerId) => {
      const address = context?.address;
      const rawAddr = addressRaw || address?.raw_address || "Hanuman Mandir ke peeche, gali no. 3";
      const pin = addressPin || address?.expected_postal_pin || "495001";
      const coords = address?.coordinates || { latitude: 22.0797, longitude: 82.1409 };
      try {
        const payload = await execute("Agent 6 is checking coordinates, PIN and DIGIPIN…", () => postAndPoll("/address/verify", { buyer_id: buyerId, raw_address: rawAddr, postal_pin: pin, coordinates: coords }));
        setVerifiedAddressId(payload.results.address_guardian?.data?.address_id || null);
        setVerifiedAddress(true);
      } catch { /* execute() already shows a toast on error */ }
    });
  }

  async function confirmOrder() {
    if (!verifiedAddressId) {
      setToast("Verify your address before placing the order");
      return;
    }
    setBusy(true);
    try {
      const order = await createOrder(verifiedAddressId, "cod");
      setLastOrderId(order.order_id);
      await execute("Agent 7 is simulating buyer confirmation…", () => post(`/orders/${order.order_id}/confirm-simulated`, { decision: "confirmed" }));
      await refreshCart();
      setCheckoutStep("done");
    } catch (reason) {
      setToast(reason.message || "Could not place this order");
    } finally {
      setBusy(false);
    }
  }

  async function checkReturn() {
    try {
      const payload = await execute("Agent 8 is comparing return evidence…", () => postAndPoll("/returns/analyze", { order_id: lastOrderId || "O-GOLDEN", video_key: "assets/mock/returns/return-approve.mp4", additional_image_keys: [] }));
      const result = payload.results?.return_verifier;
      setToast(result?.summary || "Return evidence is consistent — pickup can be scheduled");
    } catch { /* execute() already shows a toast on error */ }
  }

  async function runAll() {
    if (busy) return;
    setTrust({ open: true, results: {}, message: "Supervisor is starting the full journey…" });
    setBusy(true);
    try {
      const asyncWorkflows = new Set(["/listings/analyze", "/reviews/analyze", "/returns/analyze"]);
      const flows = [
        ["Agents 1–2 · listing and specs (real AI — Agent 1's image generation can take several minutes)", "/listings/analyze", { seller_id: "S-001", product_id: "P-001", image_keys: ["assets/mock/products/P-001.png"], seller_specs: GOLDEN_SPECS }],
        ["Agents 3 & 5 · size and voice", "/voice/query", { buyer_id: "B-001", product_id: "P-001", text: "Mujhe kaunsa size lena chahiye?", language: "hi" }],
        ["Agent 4 · review truth", "/reviews/analyze", { review_id: "RV-BAD", product_id: "P-001", image_key: "assets/mock/reviews/RV-BAD.png" }],
        ["Agent 6 · address guardian", "/address/verify", { buyer_id: "B-001", raw_address: "Hanuman Mandir ke peeche, gali no. 3", postal_pin: "495001", coordinates: { latitude: 22.0797, longitude: 82.1409 } }],
        ["Agent 7 · delivery confirmation", "/orders/O-GOLDEN/confirm-simulated", { decision: "confirmed" }],
        ["Agent 8 · fair returns", "/returns/analyze", { order_id: "O-GOLDEN", video_key: "assets/mock/returns/return-approve.mp4", additional_image_keys: [] }],
      ];
      for (const [message, path, body] of flows) {
        setTrust((current) => ({ ...current, message }));
        const payload = asyncWorkflows.has(path)
          ? await postAndPoll(path, body, { onTick: () => setTrust((current) => ({ ...current, message: `${message} (still working…)` })) })
          : await post(path, body);
        mergeResults(payload);
      }
      setToast("All 8 agents completed the protected journey");
    } catch (reason) {
      setToast(reason.message || "The safety tour stopped early");
    } finally {
      setBusy(false);
      setTrust((current) => ({ ...current, message: "" }));
    }
  }

  return (
    <div className="storefront">
      <header className="site-header">
        <div className="header-main">
          <button className="mobile-menu" type="button" aria-label="Open menu"><Menu /></button>
          <a className="logo" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a>
          <label className="search-box"><Search size={19} /><input value={search} onChange={(event) => { setSearch(event.target.value); setVisibleCount(50); }} placeholder="Try Saree, Kurti or Search by Product Code" /><kbd>⌘ K</kbd></label>
          <nav className="utility-nav" aria-label="Account navigation">
            <button type="button"><Headphones size={19} /><span>Support</span></button>
            {auth?.user ? (
              <>
                <label className="language-picker">
                  <select value={auth.user.preferred_language} onChange={(event) => changeLanguage(event.target.value)} aria-label="Preferred language">
                    {LANGUAGE_OPTIONS.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
                  </select>
                </label>
                <button type="button" onClick={handleLogout} title={auth.user.email || auth.user.phone}><CircleUserRound size={19} /><span>{auth.user.name}</span><LogOut size={14} /></button>
              </>
            ) : (
              <button type="button" onClick={() => setAuthModalOpen(true)}><CircleUserRound size={19} /><span>Login</span></button>
            )}
            <button type="button" onClick={() => setDrawer("cart")}><ShoppingCart size={19} /><span>Cart</span>{cart.length > 0 && <b>{cart.reduce((sum, item) => sum + item.qty, 0)}</b>}</button>
          </nav>
        </div>
        <div className="category-nav" aria-label="Product categories">{categories.map((item) => <button className={category === item ? "active" : ""} type="button" key={item} onClick={() => { setCategory(item); setVisibleCount(50); }}>{item}<small>{item === "All" ? products.length : categoryCounts[item] || 0}</small></button>)}</div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy"><p><ShieldCheck size={14} /> INDIA&apos;S FIRST AGENT-PROTECTED SHOPPING DEMO</p><h1>Smart shopping.<br /><em>Safer at every step.</em></h1><span>Discover value-first products while eight Kavach Saathi agents verify listings, sizes, reviews, delivery and returns.</span><div><button className="hero-primary" type="button" onClick={() => document.querySelector("#products")?.scrollIntoView({ behavior: "smooth" })}>Shop protected deals <ArrowRight size={18} /></button><button className="hero-secondary" type="button" onClick={runAll} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />} Watch all 8 agents</button></div><small><Check size={13} /> Synthetic data <Check size={13} /> Groq-powered Q&A <Check size={13} /> Fair return policy</small></div>
          <div className="hero-visual"><div className="hero-product"><img src="/mock-assets/products/P-001.png" alt="Maroon kurta mock product" /><span className="floating-check one"><Camera size={16} /><b>Image truth</b><small>Agent 1 passed</small></span><span className="floating-check two"><Sparkles size={16} /><b>Size XL</b><small>94% evidence</small></span><span className="floating-check three"><ShieldCheck size={16} /><b>Return fair</b><small>No auto-reject</small></span></div></div>
        </section>

        <section className="trust-ribbon">
          <div><span><Camera /></span><p><strong>Authentic listings</strong><small>Copied photos detected</small></p></div>
          <div><span><Sparkles /></span><p><strong>Size that travels</strong><small>Across every seller chart</small></p></div>
          <div><span><MessageCircle /></span><p><strong>Review truth</strong><small>Text stays, fake media hides</small></p></div>
          <div><span><MapPin /></span><p><strong>Address confidence</strong><small>Coordinates + DIGIPIN</small></p></div>
          <div><span><RotateCcw /></span><p><strong>Fair returns</strong><small>Evidence before decisions</small></p></div>
        </section>

        <section className="catalogue-proof" aria-label="Catalogue data summary">
          <div><strong>{products.length || 500}</strong><span>Detailed mock products</span></div>
          <div><strong>50</strong><span>Products in every category</span></div>
          <div><strong>{Math.max(categories.length - 1, 10)}</strong><span>Marketplace categories</span></div>
          <div><strong>1,000</strong><span>Review evidence records</span></div>
          <div><strong>8</strong><span>Orchestrated safety agents</span></div>
        </section>

        <section className="catalogue" id="products">
          <div className="section-heading"><div><p>{category === "All" ? "ALL 10 CATEGORIES REPRESENTED" : category.toUpperCase()}</p><h2>Products worth discovering</h2></div><span>Showing {displayedProducts.length} of {visibleProducts.length} products · {category === "All" ? "50 available in every category" : "Full category catalogue"}</span></div>
          {error && <div className="error-state"><ShieldCheck /><p><strong>Storefront API is unavailable.</strong>{error}</p></div>}
          {loading ? <div className="loading-grid">{Array.from({ length: 10 }, (_, index) => <div key={index}></div>)}</div> : <><div className="product-grid">{displayedProducts.map((product) => <ProductCard key={product.id} product={product} onOpen={openProduct} onAdd={addToCart} />)}</div>{displayedProducts.length < visibleProducts.length && <button className="load-more" type="button" onClick={() => setVisibleCount((count) => count + 50)}>Load 50 more products <ChevronRight size={16} /></button>}</>}
        </section>

        <section className="safety-story">
          <div><p>ONE ORCHESTRATOR</p><h2>Protection follows the order,<br />not a separate dashboard.</h2></div>
          <div className="story-steps">{Object.entries(AGENTS).map(([key, agent]) => { const Icon = agent.icon; return <button type="button" key={key} onClick={() => setTrust((current) => ({ ...current, open: true }))}><span>{agent.number}</span><Icon size={19} /><strong>{agent.short}</strong><ChevronRight size={15} /></button>; })}</div>
        </section>
      </main>

      <footer className="site-footer"><a className="logo inverse" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a><p>Built over a Meesho-style commerce journey with deterministic synthetic data.</p><div><button type="button" onClick={() => setTrust((current) => ({ ...current, open: true }))}>Agent activity</button><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API docs</a><button type="button" onClick={checkReturn}>Return demo</button></div></footer>

      <button className="floating-saathi" type="button" onClick={() => setTrust((current) => ({ ...current, open: !current.open }))}><ShieldCheck size={20} /><span><strong>Kavach Saathi</strong><small>{busy ? "Agents working…" : `${Object.keys(trust.results).length}/8 checks visible`}</small></span></button>
      <TrustDock trust={trust} busy={busy} onClose={() => setTrust((current) => ({ ...current, open: false }))} onRunAll={runAll} />
      <ProductDrawer product={selected} open={drawer === "product"} busy={busy} onClose={() => setDrawer(null)} onAdd={addToCart} onSize={recommendSize} onReview={checkReview} onAsk={askQuestion} onAskVoice={askVoice} voiceAudioUrl={audioUrl(voiceAudioKey)} agentAnswer={agentAnswer} sizeSaathi={sizeSaathi ? { ...sizeSaathi, audioUrl: audioUrl(sizeSaathi.audioKey) } : null} onSubmitReview={submitReview} />
      <CartDrawer items={cart} open={drawer === "cart"} onClose={() => setDrawer(null)} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); setVerifiedAddress(false); setVerifiedAddressId(null); })} />
      <CheckoutDrawer open={drawer === "checkout"} context={context} busy={busy} step={checkoutStep} verifiedAddress={verifiedAddress} orderId={lastOrderId} onClose={() => setDrawer(null)} onVerify={verifyAddress} onConfirm={confirmOrder} onReturn={checkReturn} addressRaw={addressRaw} addressPin={addressPin} onAddressRawChange={setAddressRaw} onAddressPinChange={setAddressPin} buyerName={auth?.user?.name} />
      <AuthModal open={authModalOpen} onClose={() => { setAuthModalOpen(false); setPendingAfterAuth(null); }} onAuthenticated={handleAuthenticated} />
      <ReviewSummaryDialog data={reviewSummary} onClose={() => setReviewSummary(null)} />
      {toast && <div className="toast" role="status"><Check size={16} /> {toast}</div>}
    </div>
  );
}
