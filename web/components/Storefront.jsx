"use client";

import {
  ArrowRight,
  ArrowLeft,
  BadgeCheck,
  Camera,
  Check,
  ChevronDown,
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
  Minus,
  PackageCheck,
  Package,
  Plus,
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
  Edit2,
  Trash2,
  Video,
  FileVideo,
  AlertTriangle,
  Calendar,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  addToCart as apiAddToCart,
  addWishlist,
  assetUrl,
  createOrder,
  createReturnRequest,
  createReview,
  del,
  get,
  getCart,
  getWishlist,
  listMyOrders,
  listMyReturns,
  loadAuthSession,
  login,
  logout,
  patch,
  post,
  postAndPoll,
  removeCartItem,
  removeWishlist,
  request,
  signup,
  updateCartItem,
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

function ProductCard({ product, onOpen, onAdd, onWishlist, wished, pending }) {
  const needsSize = Object.keys(product.size_chart || {}).length > 0;
  return (
    <article className="product-card" data-testid={`product-${product.id}`} data-category={product.category}>
      <div className="product-visual" role="button" tabIndex={0} onClick={() => onOpen(product)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onOpen(product); }} aria-label={`Open ${product.name}`}>
        <img src={assetUrl(product.image_url)} alt={product.name} />
        <span className="agent-checked"><ShieldCheck size={13} /> Agent checked</span>
        <button className={`heart ${wished ? "active" : ""}`} type="button" onClick={(event) => { event.stopPropagation(); onWishlist(product); }} aria-label={wished ? `Remove ${product.name} from wishlist` : `Add ${product.name} to wishlist`}><Heart size={17} fill={wished ? "currentColor" : "none"} /></button>
      </div>
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
          <button
            type="button"
            onClick={() => needsSize ? onOpen(product) : onAdd(product)}
            aria-label={needsSize ? `Choose a size for ${product.name}` : `Add ${product.name} to cart`}
            aria-busy={pending}
            disabled={pending}
          >
            {pending ? <LoaderCircle className="spin" size={16} /> : <ShoppingCart size={16} />}
          </button>
        </div>
      </div>
    </article>
  );
}

function QuantityStepper({ qty, onDecrease, onIncrease, busy = false, max = 10, compact = false }) {
  return (
    <div className={`quantity-stepper ${compact ? "compact" : ""}`} aria-label={`Quantity ${qty}`}>
      <button type="button" onClick={onDecrease} disabled={busy} aria-label="Decrease quantity">
        {busy ? <LoaderCircle className="spin" size={14} /> : <Minus size={14} />}
      </button>
      <output aria-live="polite" aria-label="Current quantity">{qty}</output>
      <button type="button" onClick={onIncrease} disabled={busy || qty >= max} aria-label={qty >= max ? "Maximum quantity 10 reached" : "Increase quantity"}>
        <Plus size={14} />
      </button>
    </div>
  );
}

function TrustDock({ trust, busy, onClose }) {
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
          <div className="dock-empty"><Sparkles size={26} /><strong>Agent activity</strong><p>Verified results from your actions will appear here.</p></div>
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
    </aside>
  );
}

function ProductPageView({ product, similarProducts, busy, cart, cartBusy, onBack, onClose, onAdd, onUpdateCart, onOpenCart, onWishlist, wished, onSize, onReview, onAsk, onAskVoice, voiceAudioUrl, agentAnswer, sizeSaathi }) {
  const [size, setSize] = useState("M");

  useEffect(() => {
    // Size Saathi arrives asynchronously from the agent run and becomes the
    // initial selection; buyers can still override it afterward.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (sizeSaathi?.size) setSize(sizeSaathi.size);
  }, [sizeSaathi?.size]);
  const [question, setQuestion] = useState("Iska fabric aur return policy batao");
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

  const sizes = useMemo(() => Object.keys(product?.size_chart || {}), [product]);
  if (!product) return null;
  const selectedSize = sizes.includes(size) ? size : sizes[0] || "Standard";
  const variantId = variantIdFor(product, selectedSize);
  const cartItem = cart.find((item) => item.product_variant_id === variantId);
  const maxQty = Math.min(10, cartItem?.stock_qty ?? product.stock ?? 10);
  return (
    <div className="product-page-shell">
      <header className="product-page-header">
        <button type="button" onClick={onBack} aria-label="Back to previous page"><ArrowLeft size={20} /></button>
        <Link className="logo" href="/" aria-label="Kavach Saathi home"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></Link>
        <div className="product-page-header-actions">
          <button type="button" onClick={() => onWishlist(product)} aria-label={wished ? "Remove from wishlist" : "Add to wishlist"}><Heart size={19} fill={wished ? "currentColor" : "none"} /></button>
          <button type="button" onClick={onOpenCart} aria-label={`Open cart with ${cart.reduce((sum, item) => sum + item.qty, 0)} items`}><ShoppingCart size={19} /><span>Cart</span>{cart.length > 0 && <b>{cart.reduce((sum, item) => sum + item.qty, 0)}</b>}</button>
          <button type="button" onClick={onClose} aria-label="Close product details"><X size={20} /></button>
        </div>
      </header>
      <main className="product-page" aria-label={product.name}>
        <div className="drawer-gallery four-view-gallery">
          {(product.catalogue_images?.length ? product.catalogue_images : ["front", "back", "left", "right"].map((angle) => ({ angle, url: product.image_url }))).map((image) => <figure key={image.angle}><img src={assetUrl(image.url)} alt={`${product.name} ${image.angle} view`} /><figcaption>{image.angle === "left" || image.angle === "right" ? `${image.angle} side` : image.angle}</figcaption></figure>)}
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

          {!!sizes.length && <div className="size-section"><div className="section-label"><strong>Select size</strong><button type="button" onClick={onSize} disabled={busy}>{busy ? <LoaderCircle className="spin" size={13} /> : <Sparkles size={13} />} Ask Size Saathi</button></div><div className="size-row">{sizes.map((item) => <button className={selectedSize === item ? "selected" : ""} type="button" key={item} onClick={() => setSize(item)}>{item}</button>)}</div>{sizeSaathi && <div className="agent-answer size-saathi-answer">{sizeSaathi.size ? <strong>Recommended: {sizeSaathi.size}</strong> : null}{sizeSaathi.message && <span>{sizeSaathi.message}</span>}{sizeSaathi.audioUrl && <audio controls src={sizeSaathi.audioUrl} style={{ width: "100%", marginTop: 8 }} />}</div>}</div>}

          <dl className="spec-list">
            <div><dt>Material</dt><dd>{product.material || product.specs.fabric}</dd></div>
            <div><dt>Best for</dt><dd>{product.occasion}</dd></div>
            <div><dt>Delivery</dt><dd>{product.delivery_days}–{product.delivery_days + 2} days</dd></div>
            <div><dt>Availability</dt><dd>{product.stock} units · {product.cod_available ? "COD available" : "Prepaid"}</dd></div>
            <div><dt>Care</dt><dd>{product.specs.wash_care}</dd></div>
            <div><dt>Return</dt><dd>{product.return_window_days} days</dd></div>
          </dl>

          <section className="product-specifications"><div className="section-label"><strong>Product specifications</strong><small>Stored listing data used for grounded comparisons</small></div><dl>
            {(product.specifications?.length ? product.specifications : Object.entries(product.specs || {}).map(([key, value]) => ({ key, label: key.replaceAll("_", " "), value }))).map((item) => <div key={item.key}><dt>{item.label}</dt><dd>{item.key.includes("color") && /^#[0-9a-f]{6}$/i.test(String(item.value)) && <i className="color-swatch" style={{ background: item.value }} />}{Array.isArray(item.value) ? item.value.join(", ") : String(item.value)}{item.unit ? ` ${item.unit}` : ""}<small>{item.verified ? "Verified" : "Seller specified"}</small></dd></div>)}
          </dl></section>

          {!!sizes.length && <section className="size-chart"><div className="section-label"><strong>Size chart</strong><small>Garment measurements in cm</small></div><div className="size-chart-scroll"><table><thead><tr><th>Size</th>{Array.from(new Set(Object.values(product.size_chart).flatMap((row) => Object.keys(row)))).map((key) => <th key={key}>{key.replaceAll("_", " ")} (cm)</th>)}</tr></thead><tbody>{Object.entries(product.size_chart).map(([chartSize, dimensions]) => <tr key={chartSize}><th>{chartSize}</th>{Array.from(new Set(Object.values(product.size_chart).flatMap((row) => Object.keys(row)))).map((key) => <td key={key}>{dimensions[key] ?? "—"}</td>)}</tr>)}</tbody></table></div></section>}

          {!!product.highlights?.length && <div className="product-highlights"><strong>Why shoppers choose it</strong><ul>{product.highlights.map((highlight) => <li key={highlight}><Check size={12} /> {highlight}</li>)}</ul>{product.presentation?.why_it_wins && <p><Sparkles size={13} /> {product.presentation.why_it_wins}</p>}</div>}

          <div className="drawer-actions">
            <button className="secondary-cta" type="button" onClick={onReview} disabled={busy}><MessageCircle size={16} /> Check review truth</button>
            {cartItem ? (
              <div className="product-cart-controls">
                <QuantityStepper qty={cartItem.qty} max={maxQty} busy={cartBusy === cartItem.id} onDecrease={() => onUpdateCart(cartItem, cartItem.qty - 1)} onIncrease={() => onUpdateCart(cartItem, cartItem.qty + 1)} />
                <button className="primary-cta" type="button" onClick={onOpenCart}>Go to cart <ArrowRight size={16} /></button>
              </div>
            ) : (
              <button className="primary-cta" type="button" onClick={() => onAdd(product, selectedSize)} disabled={cartBusy === variantId} aria-busy={cartBusy === variantId}>
                {cartBusy === variantId ? <LoaderCircle className="spin" size={16} /> : <ShoppingBag size={16} />} {cartBusy === variantId ? "Adding…" : "Add to cart"}
              </button>
            )}
          </div>

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
                        <ShieldAlert size={12} /> Photo hidden by Agent 4 — didn&apos;t match this product
                      </span>
                    )}
                  </article>
                ))}
              </div>
            </div>
          )}
          
          {!!similarProducts?.length && (
            <section className="similar-products">
              <label>Similar products verified by Saathi</label>
              <div className="product-grid">
                {similarProducts.map((p) => (
                  <button type="button" key={p.id} className="product-card" onClick={() => onOpenProduct(p.id)}>
                    <img src={assetUrl(p.image_url)} alt={p.name} />
                    <strong>{p.name}</strong>
                    <span>{money(p.price)}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </main>

      {/* Site footer on product pages (Task 12) */}
      <footer className="site-footer" style={{ marginTop: "0" }}>
        <Link className="logo inverse" href="/"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></Link>
        <p>Every product, review and return is agent-verified — no fake shortcuts.</p>
        <div>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>← Back to storefront</Link>
        </div>
      </footer>
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

function CartDrawer({ items, open, busyItem, onClose, onUpdate, onRemove, onCheckout }) {
  const total = items.reduce((sum, item) => sum + item.line_total, 0);
  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close cart" />
      <aside className="side-drawer cart-drawer" role="dialog" aria-modal="true" aria-label="Shopping cart">
        <div className="side-heading"><div><p>YOUR CART</p><h2>{items.length ? `${items.length} item${items.length > 1 ? "s" : ""}` : "Cart is empty"}</h2></div><button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button></div>
        <div className="cart-items">
          {!items.length && <div className="cart-empty"><ShoppingBag size={34} /><p>Add something you love. Kavach Saathi will verify it along the way.</p></div>}
          {items.map((item) => <article className="cart-item" key={item.id}><img src={assetUrl(item.image_url)} alt={item.product_name} /><div><strong>{item.product_name}</strong><p>Size {item.size || "Standard"}</p><span>{money(item.line_total)}</span><QuantityStepper compact qty={item.qty} max={Math.min(10, item.stock_qty)} busy={busyItem === item.id} onDecrease={() => onUpdate(item, item.qty - 1)} onIncrease={() => onUpdate(item, item.qty + 1)} /><button type="button" onClick={() => onRemove(item)} disabled={busyItem === item.id}>Remove</button></div><ShieldCheck size={18} /></article>)}
        </div>
        {!!items.length && <div className="cart-total"><div><span>Product total</span><strong>{money(total)}</strong></div><div><span>Delivery</span><strong className="free">FREE</strong></div><div className="grand-total"><span>Order total</span><strong>{money(total)}</strong></div><button className="primary-cta" type="button" onClick={onCheckout}>Continue to secure checkout <ArrowRight size={17} /></button><p><ShieldCheck size={13} /> Address and delivery consent will be verified before dispatch.</p></div>}
      </aside>
    </div>
  );
}

function AccountDataDrawer({ type, open, orders, wishlist, returns, onClose, onOpenProduct, onRemoveWishlist, onStartReturn, onStartReview, onViewReturn, onSubmitFitFeedback }) {
  const title = type === "orders" ? "My Orders" : type === "wishlist" ? "My Wishlist" : "My Returns";
  const items = type === "orders" ? orders : type === "wishlist" ? wishlist : returns;

  function statusColor(s) {
    if (["DELIVERED", "RETURN_APPROVED", "CLOSED"].includes(s)) return "#16a34a";
    if (["RETURN_INITIATED", "RETURN_UNDER_REVIEW", "MANUAL_INSPECTION"].includes(s)) return "#d97706";
    if (["CANCELLED", "RETURN_REJECTED"].includes(s)) return "#e5484d";
    return "#6366f1";
  }

  // A different item's return may have already moved the order out of DELIVERED
  // (e.g. into RETURN_INITIATED) -- any of these still means the order was
  // delivered, so its other, untouched items should still show Return/Exchange/Review.
  const POST_DELIVERY_STATUSES = ["DELIVERED", "RETURN_INITIATED", "RETURN_UNDER_REVIEW", "RETURN_APPROVED", "RETURN_REJECTED", "MANUAL_INSPECTION", "CLOSED"];

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label={`Close ${title}`} />
      <aside className="side-drawer account-data-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="side-heading">
          <div><p>YOUR ACCOUNT</p><h2>{title}</h2></div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>
        <div className="account-data-list">
          {!items.length && <div className="cart-empty"><Package size={34} /><p>No {title.toLowerCase()} yet.</p></div>}

          {type === "orders" && orders.map((order) => (
            <article className="account-record" key={order.id} style={{ borderLeft: `3px solid ${statusColor(order.status)}`, paddingLeft: "12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "6px" }}>
                <div>
                  <strong style={{ fontSize: "14px" }}>{order.id}</strong>
                  {order.exchange_tag && <span style={{ marginLeft: "6px", background: "#ede9fe", color: "#7c3aed", padding: "1px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "600" }}>EXCHANGE</span>}
                </div>
                <span style={{ fontSize: "11px", fontWeight: "600", color: statusColor(order.status), background: "#f8fafc", padding: "2px 8px", borderRadius: "4px" }}>{order.status}</span>
              </div>
              <p style={{ margin: "0 0 8px", color: "#64748b", fontSize: "13px" }}>
                {new Date(order.created_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })} · {money(order.total_amount)} · {order.payment_mode?.toUpperCase()}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "10px" }}>
                {order.items.map((item) => (
                  <div key={`${order.id}-${item.product_id}`} style={{ display: "flex", flexDirection: "column", gap: "6px", background: "#f8fafc", border: "1px solid var(--border)", borderRadius: "6px", padding: "8px" }}>
                    <button type="button" onClick={() => onOpenProduct(item.product_id)} style={{ display: "flex", alignItems: "center", gap: "10px", background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", width: "100%" }}>
                      <img src={assetUrl(item.image_url)} alt="" style={{ width: "40px", height: "40px", objectFit: "cover", borderRadius: "4px", flexShrink: 0 }} />
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontWeight: "600", fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.product_name}</span>
                        <small style={{ color: "#64748b" }}>Size {item.size || "Standard"} · Qty {item.qty}</small>
                      </span>
                      {item.already_reviewed && <span style={{ fontSize: "11px", color: "#16a34a", flexShrink: 0 }}>✓ Reviewed</span>}
                    </button>
                    {item.return_info && (
                      <div style={{ background: "#fef9f0", border: "1px solid #fde68a", borderRadius: "6px", padding: "6px 8px", fontSize: "12px" }}>
                        <span style={{ fontWeight: "600", color: "#92400e" }}>{item.return_info.return_type === "exchange" ? "Exchange" : "Return"}</span>
                        {" — "}
                        <span style={{ color: "#78350f", textTransform: "capitalize" }}>{(item.return_info.status || "").replace(/_/g, " ")}</span>
                        {item.return_info.decision && <span style={{ marginLeft: "4px", color: "#64748b" }}>· {item.return_info.decision}</span>}
                        {item.return_info.confidence_score != null && <span style={{ marginLeft: "4px", color: "#64748b" }}>· Agent: {item.return_info.confidence_score}%</span>}
                        {item.return_info.pickup_date && <div style={{ color: "#64748b", marginTop: "2px" }}>Pickup: {new Date(item.return_info.pickup_date).toLocaleDateString("en-IN")}</div>}
                        {item.return_info.refund_status && <div style={{ color: "#64748b", marginTop: "2px" }}>Refund: {item.return_info.refund_status}</div>}
                        <button
                          type="button"
                          className="secondary-cta compact"
                          style={{ marginTop: "6px", width: "100%", fontSize: "11px", padding: "4px 8px" }}
                          onClick={() => onViewReturn(item.return_info.id)}
                        >
                          View Status &amp; Verification Page
                        </button>
                      </div>
                    )}
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      {POST_DELIVERY_STATUSES.includes(order.status) && !item.return_info && (
                        <>
                          <button className="secondary-cta compact" type="button" style={{ flex: 1, fontSize: "12px" }} onClick={() => onStartReturn(order.id, item.product_id, "refund")}><RotateCcw size={13} /> Return</button>
                          <button className="secondary-cta compact" type="button" style={{ flex: 1, fontSize: "12px" }} onClick={() => onStartReturn(order.id, item.product_id, "exchange")}><ArrowRight size={13} /> Exchange</button>
                        </>
                      )}
                      {POST_DELIVERY_STATUSES.includes(order.status) && !item.already_reviewed && (
                        <button className="secondary-cta compact" type="button" style={{ flex: 1, fontSize: "12px" }} onClick={() => onStartReview(item.product_id, order.id)}><Star size={13} /> Rate &amp; Review</button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              {POST_DELIVERY_STATUSES.includes(order.status) && !order.fit_feedback && (
                <div style={{ background: "#f8fafc", border: "1px solid var(--border)", borderRadius: "6px", padding: "8px 10px", marginBottom: "8px" }}>
                  <p style={{ margin: "0 0 6px", fontSize: "13px", fontWeight: "600" }}>How did it fit?</p>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <button type="button" className="secondary-cta compact" style={{ flex: 1, fontSize: "12px" }} onClick={() => onSubmitFitFeedback(order.id, "tight")}>Too tight</button>
                    <button type="button" className="secondary-cta compact" style={{ flex: 1, fontSize: "12px" }} onClick={() => onSubmitFitFeedback(order.id, "good")}>Good fit</button>
                    <button type="button" className="secondary-cta compact" style={{ flex: 1, fontSize: "12px" }} onClick={() => onSubmitFitFeedback(order.id, "loose")}>Too loose</button>
                  </div>
                </div>
              )}
              {!["DELIVERED", "RETURN_INITIATED", "RETURN_UNDER_REVIEW", "MANUAL_INSPECTION", "RETURN_APPROVED", "CLOSED", "CANCELLED"].includes(order.status) && (
                <small style={{ color: "#94a3b8", fontSize: "12px" }}>Return available after delivery</small>
              )}
            </article>
          ))}

          {type === "wishlist" && wishlist.map((item) => (
            <article className="account-record wishlist-record" key={item.id}>
              <button type="button" onClick={() => onOpenProduct(item.product.id)}>
                <img src={assetUrl(item.product.image_url)} alt="" />
                <span><strong>{item.product.name}</strong><small>{money(item.product.price)} · {item.product.stock} available</small></span>
              </button>
              <button className="secondary-cta" type="button" onClick={() => onRemoveWishlist(item.product.id)}>Remove</button>
            </article>
          ))}

          {type === "returns" && returns.map((item) => (
            <article className="account-record" key={item.id} style={{ borderLeft: `3px solid ${item.decision === "approve" ? "#16a34a" : item.decision === "manual_inspection" ? "#d97706" : "#6366f1"}`, paddingLeft: "12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "4px" }}>
                <strong style={{ fontSize: "14px" }}>{item.id}</strong>
                <span style={{ fontSize: "11px", background: "#f1f5f9", padding: "2px 6px", borderRadius: "4px", color: "#475569" }}>{(item.return_type || "refund").toUpperCase()}</span>
              </div>
              <p style={{ margin: "0 0 4px", color: "#64748b", fontSize: "13px" }}>Order {item.order_id}</p>
              <p style={{ margin: "0 0 6px", fontSize: "13px" }}>{item.reason}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", fontSize: "12px", color: "#64748b" }}>
                <span>Status: <strong style={{ color: "#334155" }}>{(item.status || "pending_evidence").replace(/_/g, " ")}</strong></span>
                {item.decision && <span>· Decision: <strong style={{ color: "#334155" }}>{item.decision.replace(/_/g, " ")}</strong></span>}
                {item.confidence_score != null && <span>· Agent: <strong style={{ color: "#334155" }}>{item.confidence_score}%</strong></span>}
              </div>
              {item.pickup_date && <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#16a34a" }}>Pickup: {new Date(item.pickup_date).toLocaleDateString("en-IN")}</p>}
              {item.refund_status && <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#6366f1" }}>Refund: {item.refund_status}</p>}
              {item.replacement_order_id && <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#7c3aed" }}>Replacement: {item.replacement_order_id}</p>}
              <button 
                type="button" 
                className="secondary-cta compact" 
                style={{ marginTop: "10px", width: "100%", fontSize: "12px" }}
                onClick={() => onViewReturn(item.id)}
              >
                {item.status === "pending_evidence" || item.status === "needs_evidence" ? "Upload Return Evidence" : "View AI Analysis & Status"}
              </button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}

function ReturnVerificationDrawer({ open, returnId, returns, orders, onClose, onRefreshData }) {
  const [videoFile, setVideoFile] = useState(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(10);
  const [mediaStream, setMediaStream] = useState(null);
  const [mediaRecorder, setMediaRecorder] = useState(null);
  
  const videoPreviewRef = useRef(null);
  const recordedChunksRef = useRef([]);

  const record = returns.find((r) => r.id === returnId);
  const order = record ? orders.find((o) => o.id === record.order_id) : null;
  const returnedItem = order?.items?.find((item) => item.product_id === record?.product_id);

  useEffect(() => {
    return () => {
      if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
    };
  }, [videoPreviewUrl]);

  if (!open || !record) return null;

  async function startRecording() {
    recordedChunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      setMediaStream(stream);
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream;
      }
      const recorder = new MediaRecorder(stream, { mimeType: "video/webm" });
      setMediaRecorder(recorder);
      
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          recordedChunksRef.current.push(e.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(recordedChunksRef.current, { type: "video/mp4" });
        const file = new File([blob], "return-video.mp4", { type: "video/mp4" });
        setVideoFile(file);
        setVideoPreviewUrl(URL.createObjectURL(blob));
        
        stream.getTracks().forEach((track) => track.stop());
        setMediaStream(null);
        setRecording(false);
      };

      recorder.start();
      setRecording(true);
      setRecordingSeconds(10);

      const interval = setInterval(() => {
        setRecordingSeconds((prev) => {
          if (prev <= 1) {
            clearInterval(interval);
            recorder.stop();
            return 0;
          }
          return prev - 1;
        });
      }, 1000);

    } catch (err) {
      alert("Could not access camera: " + err.message);
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      setMediaStream(null);
    }
    setRecording(false);
  }

  function handleFileSelect(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("video/")) {
      alert("Please select a valid video file.");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      alert("File is too large. Please select a video under 50MB.");
      return;
    }
    setVideoFile(file);
    setVideoPreviewUrl(URL.createObjectURL(file));
  }

  async function handleSubmitEvidence() {
    if (!videoFile) return;
    setUploading(true);
    setStatusText("Obtaining upload slot...");
    try {
      const presignData = await post("/uploads/presign", {
        filename: videoFile.name || "video.mp4",
        kind: "return"
      });

      setStatusText("Uploading video to secure storage...");
      const response = await fetch(presignData.upload_url, {
        method: "PUT",
        headers: {
          "Content-Type": videoFile.type || "video/mp4"
        },
        body: videoFile
      });

      if (!response.ok) {
        throw new Error(`Upload failed with status ${response.status}`);
      }

      setStatusText("Agent 8 is evaluating return evidence...");
      await postAndPoll("/returns/analyze", {
        order_id: record.order_id,
        product_id: record.product_id,
        video_key: presignData.object_key,
        additional_image_keys: []
      });

      setStatusText("Analysis complete!");
      setTimeout(() => {
        setUploading(false);
        onRefreshData();
      }, 1500);

    } catch (err) {
      alert("Failed to verify return: " + err.message);
      setUploading(false);
      setStatusText("");
    }
  }

  return (
    <div className="drawer-layer open" style={{ zIndex: 100 }}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close Return Verification" />
      <aside className="side-drawer" role="dialog" aria-modal="true" style={{ width: "min(600px, 100vw)", padding: "24px", display: "flex", flexDirection: "column", gap: "20px", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <p style={{ margin: 0, fontSize: "11px", fontWeight: "bold", color: "var(--plum)" }}>AI RETURN VERIFICATION</p>
            <h2 style={{ margin: 0, fontFamily: "Georgia, serif", fontSize: "20px" }}>Request ID: {record.id}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: "none", border: "none", cursor: "pointer" }}><X size={20} /></button>
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: "10px", padding: "12px", background: "var(--soft)" }}>
          <span style={{ fontSize: "12px", color: "var(--muted)" }}>Original Order: <strong>{record.order_id}</strong></span>
          {returnedItem && (
            <div style={{ display: "flex", gap: "10px", marginTop: "8px", alignItems: "center" }}>
              <img src={assetUrl(returnedItem.image_url)} alt="" style={{ width: "40px", height: "40px", objectFit: "cover", borderRadius: "6px" }} />
              <div style={{ flex: 1 }}>
                <span style={{ display: "block", fontSize: "13px", fontWeight: "bold" }}>{returnedItem.product_name}</span>
                <small style={{ color: "var(--muted)" }}>Size: {returnedItem.size || "Standard"} · Qty: {returnedItem.qty}</small>
              </div>
            </div>
          )}
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: "12px", padding: "16px", background: "white", display: "flex", flexDirection: "column", gap: "12px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid var(--line)", paddingBottom: "10px" }}>
            <span>Status: <strong style={{ color: "var(--plum)", textTransform: "uppercase" }}>{record.status?.replace(/_/g, " ")}</strong></span>
            {record.confidence_score != null && (
              <span>Agent Confidence: <strong style={{ color: record.confidence_score >= 75 ? "#16a34a" : record.confidence_score >= 40 ? "#d97706" : "#ef4444" }}>{record.confidence_score}%</strong></span>
            )}
          </div>
          
          <div style={{ fontSize: "13px", display: "flex", flexDirection: "column", gap: "6px" }}>
            {record.decision && <div>Decision: <strong>{record.decision.replace(/_/g, " ").toUpperCase()}</strong></div>}
            {record.pickup_date && <div>Pickup Date: <strong>{new Date(record.pickup_date).toLocaleDateString("en-IN")} ({record.pickup_status})</strong></div>}
            {record.refund_status && <div>Refund Status: <strong>{record.refund_status.toUpperCase()} ({record.refund_masked_details || "N/A"})</strong></div>}
            {record.replacement_order_id && <div>Replacement Order ID: <strong>{record.replacement_order_id}</strong></div>}
          </div>
        </div>

        {(record.status === "pending_evidence" || record.status === "needs_evidence") && (
          <div style={{ border: "1px solid var(--line)", borderRadius: "12px", padding: "16px", background: "white", display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--plum)", fontWeight: "bold", fontSize: "14px" }}>
              <Camera size={16} /> Provide Return Video Evidence
            </div>
            <p style={{ margin: 0, fontSize: "12px", color: "var(--muted)", lineHeight: "1.4" }}>
              Please record or upload a continuous 10-second 360° video showing the product, front, back, tag, packaging, and the shipping label clearly.
            </p>

            {recording ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: "center" }}>
                <video ref={videoPreviewRef} autoPlay muted playsInline style={{ width: "100%", maxHeight: "200px", background: "black", borderRadius: "8px" }} />
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#ef4444", fontSize: "14px", fontWeight: "bold" }}>
                  <Video size={16} className="spin" /> Recording: {recordingSeconds}s remaining
                </div>
                <button type="button" className="secondary-cta" onClick={stopRecording} style={{ borderColor: "#ef4444", color: "#ef4444" }}>Stop Recording</button>
              </div>
            ) : (
              <div style={{ display: "flex", gap: "10px" }}>
                <button type="button" className="primary-cta" style={{ flex: 1 }} onClick={startRecording}>
                  <Camera size={16} /> Use Camera
                </button>
                <label className="secondary-cta" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", cursor: "pointer" }}>
                  <FileVideo size={16} /> Select File
                  <input type="file" accept="video/*" onChange={handleFileSelect} style={{ display: "none" }} />
                </label>
              </div>
            )}

            {videoPreviewUrl && !recording && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: "center", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
                <video src={videoPreviewUrl} controls style={{ width: "100%", maxHeight: "200px", borderRadius: "8px" }} />
                <button 
                  type="button" 
                  className="primary-cta" 
                  onClick={handleSubmitEvidence} 
                  disabled={uploading}
                  style={{ width: "100%" }}
                >
                  {uploading ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}
                  {uploading ? statusText : "Submit Evidence for Agent 8 Review"}
                </button>
              </div>
            )}
          </div>
        )}

        {record.status_timeline && record.status_timeline.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <span style={{ fontSize: "13px", fontWeight: "bold", color: "var(--muted)" }}>Status Timeline</span>
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", borderLeft: "2px solid var(--line)", paddingLeft: "15px", marginLeft: "10px" }}>
              {record.status_timeline.map((entry, index) => (
                <div key={index} style={{ position: "relative" }}>
                  <div style={{ position: "absolute", left: "-21px", top: "3px", width: "10px", height: "10px", borderRadius: "50%", background: "var(--plum)" }} />
                  <div style={{ fontSize: "13px", fontWeight: "bold", textTransform: "capitalize" }}>{entry.status.replace(/_/g, " ")}</div>
                  <small style={{ color: "var(--muted)", display: "block" }}>{new Date(entry.timestamp).toLocaleString("en-IN")}</small>
                  {entry.notes && <p style={{ margin: "4px 0 0 0", fontSize: "12px", color: "var(--muted)" }}>{entry.notes}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function CheckoutDrawer({
  open,
  busy,
  step,
  orderId,
  onClose,
  onConfirm,
  onConfirmPrepaid,
  addresses,
  onManageAddresses,
  buyerName,
  orderSummary,
  onGoOrders,
}) {
  const [selectedAddressId, setSelectedAddressId] = useState("");
  const [paymentMode, setPaymentMode] = useState("cod");

  useEffect(() => {
    if (open && addresses.length) {
      const def = addresses.find((a) => a.is_default);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedAddressId(def ? def.id : addresses[0].id);
    }
  }, [open, addresses]);

  const selectedAddress = addresses.find((a) => a.id === selectedAddressId);
  const isValidAddress =
    selectedAddress &&
    selectedAddress.phone_verified &&
    selectedAddress.validation_status === "valid" &&
    selectedAddress.digipin;

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close checkout" />
      <aside className="side-drawer checkout-drawer" role="dialog" aria-modal="true" aria-label="Secure checkout" style={{ width: "min(500px, 100vw)" }}>
        <div className="side-heading">
          <div><p>SECURE CHECKOUT</p><h2>{step === "done" ? "Order protected" : "Delivery details"}</h2></div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>
        <div className="checkout-progress">
          <span className="complete"><Check size={12} /> Cart</span>
          <i></i>
          <span className={isValidAddress ? "complete" : "active"}>Address</span>
          <i></i>
          <span className={step === "done" ? "complete" : ""}>Confirm</span>
        </div>
        {step !== "done" ? (
          <div className="checkout-body" style={{ display: "flex", flexDirection: "column", gap: "20px", padding: "16px", overflowY: "auto", flex: 1 }}>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <strong style={{ fontSize: "15px" }}>Deliver to:</strong>
                <button type="button" className="secondary-cta compact" onClick={onManageAddresses} style={{ fontSize: "11px", padding: "4px 8px" }}>
                  Manage Addresses
                </button>
              </div>

              {!addresses.length ? (
                <div style={{ border: "1px dashed var(--border)", padding: "16px", borderRadius: "8px", textAlign: "center" }}>
                  <p style={{ margin: "0 0 8px", color: "#64748b", fontSize: "14px" }}>No saved addresses found.</p>
                  <button type="button" className="primary-cta compact" onClick={onManageAddresses}>
                    + Add New Address
                  </button>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {addresses.map((addr) => (
                    <label key={addr.id} style={{ display: "flex", gap: "10px", border: "1px solid", borderColor: selectedAddressId === addr.id ? "var(--accent, #e5484d)" : "var(--border)", padding: "12px", borderRadius: "8px", cursor: "pointer", background: selectedAddressId === addr.id ? "#fdf0f0" : "white" }}>
                      <input type="radio" name="checkout_address" checked={selectedAddressId === addr.id} onChange={() => setSelectedAddressId(addr.id)} style={{ marginTop: "4px" }} />
                      <div style={{ fontSize: "14px", flex: 1 }}>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <strong>{addr.recipient_name} ({addr.address_type})</strong>
                          {addr.is_default && <span style={{ color: "#16a34a", fontSize: "11px", fontWeight: "bold" }}>Default</span>}
                        </div>
                        <p style={{ margin: "2px 0 0", color: "#334155" }}>
                          {addr.address_line1}, {addr.city}, {addr.state} - {addr.postal_pin}
                        </p>
                        <div style={{ display: "flex", gap: "8px", marginTop: "6px", fontSize: "11px" }}>
                          {addr.phone_verified ? (
                            <span style={{ color: "#16a34a" }}>✓ Phone Verified</span>
                          ) : (
                            <span style={{ color: "#ef4444" }}>✗ Phone Unverified</span>
                          )}
                          {addr.validation_status === "valid" ? (
                            <span style={{ color: "#16a34a" }}>✓ Address Valid</span>
                          ) : (
                            <span style={{ color: "#ef4444" }}>✗ Address Invalid</span>
                          )}
                          {addr.digipin && <span style={{ color: "#475569" }}>DIGIPIN: {addr.digipin}</span>}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {isValidAddress && (
              <div>
                <strong style={{ fontSize: "15px", display: "block", marginBottom: "8px" }}>Payment Mode:</strong>
                <div style={{ display: "flex", gap: "12px" }}>
                  <label style={{ display: "flex", gap: "8px", flex: 1, border: "1px solid", borderColor: paymentMode === "cod" ? "var(--accent, #e5484d)" : "var(--border)", padding: "12px", borderRadius: "8px", cursor: "pointer", background: paymentMode === "cod" ? "#fdf0f0" : "white" }}>
                    <input type="radio" checked={paymentMode === "cod"} onChange={() => setPaymentMode("cod")} style={{ display: "none" }} />
                    <div style={{ opacity: paymentMode === "cod" ? 1 : 0.6 }}>
                      <strong>Cash on Delivery</strong>
                      <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>Pay with cash on arrival</p>
                    </div>
                  </label>
                  <label style={{ display: "flex", gap: "8px", flex: 1, border: "1px solid", borderColor: paymentMode === "prepaid" ? "var(--accent, #e5484d)" : "var(--border)", padding: "12px", borderRadius: "8px", cursor: "pointer", background: paymentMode === "prepaid" ? "#fdf0f0" : "white" }}>
                    <input type="radio" checked={paymentMode === "prepaid"} onChange={() => setPaymentMode("prepaid")} style={{ display: "none" }} />
                    <div style={{ opacity: paymentMode === "prepaid" ? 1 : 0.6 }}>
                      <strong>Prepaid (Razorpay)</strong>
                      <p style={{ margin: "2px 0 0", fontSize: "12px", color: "#64748b" }}>Secure online sandbox</p>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {isValidAddress && (
              <div className="consent-box" style={{ margin: 0 }}><Truck size={19} /><div><strong>Agent 7 delivery confirmation</strong><p>A real verification call confirms buyer availability before delivery.</p></div></div>
            )}

            {selectedAddress && (
              <div>
                {!isValidAddress ? (
                  <div style={{ background: "#fef3c7", border: "1px solid #fde68a", padding: "12px", borderRadius: "8px", color: "#d97706", fontSize: "13px" }}>
                    <strong>Validation failed:</strong> This address cannot be used for checkout. Please make sure the phone number is verified via OTP and coordinates match the address details.
                  </div>
                ) : (
                  <button
                    className="primary-cta wide"
                    type="button"
                    onClick={() => paymentMode === "cod" ? onConfirm(selectedAddressId) : onConfirmPrepaid(selectedAddressId)}
                    disabled={busy}
                  >
                    {busy ? <LoaderCircle className="spin" size={17} /> : <PackageCheck size={17} />}
                    {paymentMode === "cod" ? "Confirm availability & place COD order" : "Pay securely via Razorpay"}
                  </button>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="success-state">
            <span><PackageCheck size={40} /></span>
            <h3>Order {orderId} is protected</h3>
            <p>{orderSummary?.paymentMode === "prepaid" ? "Payment verified" : "Cash on delivery confirmed"}. The order is now visible in My Orders.</p>
            <div>
              <strong>{money(orderSummary?.amount || 0)} · {orderSummary?.paymentMode?.toUpperCase()}</strong>
              <br />
              <span>{orderSummary?.address?.address_line1}, {orderSummary?.address?.city} · DIGIPIN {orderSummary?.address?.digipin}</span>
              <br />
              <Check size={15} /> Agent 6 verified address
              <br />
              <Check size={15} /> Agent 7 captured consent
            </div>
            <button className="primary-cta wide" type="button" onClick={onGoOrders}>
              Go to My Orders
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}

function AddressManagerDrawer({ open, onClose, buyerId }) {
  const [addresses, setAddresses] = useState([]);
  const [mode, setMode] = useState("list");
  const [formData, setFormData] = useState({
    recipient_name: "",
    phone: "",
    address_line1: "",
    address_line2: "",
    locality: "",
    city: "",
    district: "",
    state: "",
    postal_pin: "",
    country: "India",
    address_type: "Home",
    is_default: false
  });
  const [editingId, setEditingId] = useState(null);
  const [coords, setCoords] = useState({ latitude: 22.0797, longitude: 82.1409 });
  const [phoneVerified, setPhoneVerified] = useState(false);
  const [addressSessionId, setAddressSessionId] = useState("");
  const [verificationSessionId, setVerificationSessionId] = useState("");
  const [showOtpModal, setShowOtpModal] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const mapRef = useRef(null);
  const leafletMap = useRef(null);
  const marker = useRef(null);

  useEffect(() => {
    if (open && buyerId) {
      loadAddresses();
    }
  }, [open, buyerId]);

  async function loadAddresses() {
    try {
      const data = await get("/addresses");
      setAddresses(data);
    } catch (err) {
      setError("Failed to load addresses: " + err.message);
    }
  }

  useEffect(() => {
    if (cooldown > 0) {
      const timer = setTimeout(() => setCooldown(cooldown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [cooldown]);

  useEffect(() => {
    if ((mode === "add" || mode === "edit") && typeof window !== "undefined" && open) {
      if (!window.L) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);

        const script = document.createElement("script");
        script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
        script.onload = initMap;
        document.head.appendChild(script);
      } else {
        setTimeout(initMap, 100);
      }
    }

    return () => {
      if (leafletMap.current) {
        leafletMap.current.remove();
        leafletMap.current = null;
        marker.current = null;
      }
    };

    function initMap() {
      if (!window.L || !mapRef.current || leafletMap.current) return;
      const L = window.L;
      const initialCoords = [coords.latitude, coords.longitude];
      leafletMap.current = L.map(mapRef.current).setView(initialCoords, 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap"
      }).addTo(leafletMap.current);
      const customIcon = L.icon({
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
        iconSize: [25, 41],
        iconAnchor: [12, 41]
      });
      marker.current = L.marker(initialCoords, { draggable: true, icon: customIcon }).addTo(leafletMap.current);
      marker.current.on("dragend", () => {
        const pos = marker.current.getLatLng();
        setCoords({ latitude: pos.lat, longitude: pos.lng });
      });

      leafletMap.current.on("click", (e) => {
        marker.current.setLatLng(e.latlng);
        setCoords({ latitude: e.latlng.lat, longitude: e.latlng.lng });
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, open]);

  async function handleGeocode() {
    setBusy(true);
    setError("");
    try {
      const validation = await post("/addresses/reverse-geocode", coords);
      const city = validation.city || "";
      const district = validation.district || validation.city || "";
      const state = validation.state || "";
      const postal_pin = validation.postal_pin || "";
      const label = validation.label || "";

      setFormData((prev) => ({
        ...prev,
        city,
        district,
        state,
        postal_pin,
        address_line1: prev.address_line1 || label
      }));
      setSuccess("Location geocoded successfully! Fields updated.");
    } catch (err) {
      setError("Geocoding failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleManualGeocode() {
    setBusy(true);
    setError("");
    try {
      const result = await post("/addresses/geocode", formData);
      const next = { latitude: result.latitude, longitude: result.longitude };
      setCoords(next);
      if (leafletMap.current && marker.current) {
        marker.current.setLatLng([next.latitude, next.longitude]);
        leafletMap.current.setView([next.latitude, next.longitude], 16);
      }
      setSuccess("Address located. Review the map pin, then verify your phone and save.");
    } catch (err) {
      setError("Address lookup failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setError("This browser does not support location access.");
      return;
    }
    setBusy(true);
    setError("");
    navigator.geolocation.getCurrentPosition(
      async ({ coords: position }) => {
        const next = { latitude: position.latitude, longitude: position.longitude };
        setCoords(next);
        if (leafletMap.current && marker.current) {
          marker.current.setLatLng([next.latitude, next.longitude]);
          leafletMap.current.setView([next.latitude, next.longitude], 16);
        }
        try {
          const result = await post("/addresses/reverse-geocode", next);
          setFormData((previous) => ({
            ...previous,
            address_line1: previous.address_line1 || result.label || "",
            city: result.city || previous.city,
            district: result.district || result.city || previous.district,
            state: result.state || previous.state,
            postal_pin: result.postal_pin || previous.postal_pin,
          }));
          setSuccess("Current location captured. Adjust the pin if needed.");
        } catch (err) {
          setError("Location captured, but address lookup failed: " + err.message);
        } finally {
          setBusy(false);
        }
      },
      (reason) => {
        setBusy(false);
        setError(reason.message || "Location permission was not granted.");
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  }

  async function triggerOtp() {
    if (!formData.phone) {
      setError("Please enter a valid phone number first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await post("/addresses/otp/send", {
        phone: formData.phone,
        address_session_id: addressSessionId,
      });
      setCooldown(60);
      setShowOtpModal(true);
      if (res.demo_otp) {
        setSuccess(`Demo OTP: ${res.demo_otp}`);
      } else {
        setSuccess("OTP sent successfully to your phone.");
      }
    } catch (err) {
      setError("Failed to send OTP: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyOtp() {
    setBusy(true);
    setError("");
    try {
      const result = await post("/addresses/otp/verify", {
        phone: formData.phone,
        otp: otpCode,
        address_session_id: addressSessionId,
      });
      setVerificationSessionId(result.verification_session_id);
      setPhoneVerified(true);
      setShowOtpModal(false);
      setSuccess("Phone number verified successfully!");
    } catch (err) {
      setError("Incorrect OTP code. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!phoneVerified) {
      setError("Please verify the phone number via OTP first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        ...formData,
        latitude: coords.latitude,
        longitude: coords.longitude,
        ...(verificationSessionId ? { verification_session_id: verificationSessionId } : {}),
      };
      if (mode === "add") {
        await post("/addresses", payload);
      } else {
        await request(`/addresses/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(payload)
        });
      }
      setSuccess("Address saved successfully!");
      setMode("list");
      loadAddresses();
    } catch (err) {
      setError("Failed to save address: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Are you sure you want to delete this address?")) return;
    try {
      await del(`/addresses/${id}`);
      loadAddresses();
      setSuccess("Address deleted successfully.");
    } catch (err) {
      setError("Failed to delete address: " + err.message);
    }
  }

  async function handleSetDefault(id) {
    try {
      await post(`/addresses/${id}/default`);
      loadAddresses();
      setSuccess("Default address updated.");
    } catch (err) {
      setError("Failed to set default: " + err.message);
    }
  }

  function startAdd() {
    setFormData({
      recipient_name: "",
      phone: "",
      address_line1: "",
      address_line2: "",
      locality: "",
      city: "",
      district: "",
      state: "",
      postal_pin: "",
      country: "India",
      address_type: "Home",
      is_default: false
    });
    setCoords({ latitude: 22.0797, longitude: 82.1409 });
    setPhoneVerified(false);
    setAddressSessionId(crypto.randomUUID().replaceAll("-", ""));
    setVerificationSessionId("");
    setMode("add");
    setError("");
    setSuccess("");
  }

  function startEdit(addr) {
    setFormData({
      recipient_name: addr.recipient_name,
      phone: addr.phone,
      address_line1: addr.address_line1,
      address_line2: addr.address_line2 || "",
      locality: addr.locality || "",
      city: addr.city,
      district: addr.district,
      state: addr.state,
      postal_pin: addr.postal_pin,
      country: addr.country,
      address_type: addr.address_type,
      is_default: addr.is_default
    });
    setCoords({ latitude: addr.latitude, longitude: addr.longitude });
    setPhoneVerified(addr.phone_verified);
    setAddressSessionId(crypto.randomUUID().replaceAll("-", ""));
    setVerificationSessionId("");
    setEditingId(addr.id);
    setMode("edit");
    setError("");
    setSuccess("");
  }

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close address manager" />
      <aside className="side-drawer" role="dialog" aria-modal="true" aria-label="Manage Addresses" style={{ width: "min(550px, 100vw)" }}>
        <div className="side-heading">
          <div><p>YOUR PROFILE</p><h2>{mode === "list" ? "Manage Addresses" : mode === "add" ? "Add Address" : "Edit Address"}</h2></div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>

        {error && <div className="toast error" style={{ position: "static", margin: "16px", background: "#fdf0f0", color: "#e5484d", border: "1px solid #f8c8c9" }}>{error}</div>}
        {success && <div className="toast success" style={{ position: "static", margin: "16px", background: "#f0fdf4", color: "#16a34a", border: "1px solid #bbf7d0" }}>{success}</div>}

        <div className="account-data-list" style={{ padding: "0 16px 24px", overflowY: "auto", flex: 1 }}>
          {mode === "list" ? (
            <>
              <button className="primary-cta wide" onClick={startAdd} style={{ marginBottom: "16px" }}>
                <Plus size={16} /> Add New Address
              </button>
              {!addresses.length && <div className="cart-empty" style={{ margin: "40px 0" }}><MapPin size={34} /><p>No saved addresses yet.</p></div>}
              {addresses.map((addr) => (
                <article className="account-record" key={addr.id} style={{ display: "flex", flexDirection: "column", gap: "8px", border: "1px solid var(--border)", borderRadius: "8px", padding: "16px", marginBottom: "12px", background: "#fafafa" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <strong style={{ fontSize: "16px" }}>{addr.recipient_name}</strong>
                      <span className={`badge ${addr.address_type.toLowerCase()}`} style={{ marginLeft: "8px", padding: "2px 6px", fontSize: "11px", borderRadius: "4px", background: "#e2e8f0", color: "#475569" }}>{addr.address_type}</span>
                      {addr.is_default && <span style={{ marginLeft: "8px", padding: "2px 6px", fontSize: "11px", borderRadius: "4px", background: "#dcfce7", color: "#16a34a", fontWeight: "bold" }}>Default</span>}
                    </div>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <button type="button" onClick={() => startEdit(addr)} title="Edit" style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}><Edit2 size={16} /></button>
                      <button type="button" onClick={() => handleDelete(addr.id)} title="Delete" style={{ background: "none", border: "none", cursor: "pointer", color: "#ef4444" }}><Trash2 size={16} /></button>
                    </div>
                  </div>
                  <p style={{ margin: 0, color: "#334155" }}>
                    {addr.address_line1}, {addr.address_line2 && `${addr.address_line2}, `}{addr.locality && `${addr.locality}, `}{addr.city}, {addr.state} - {addr.postal_pin}
                  </p>
                  <p style={{ margin: 0, fontSize: "13px", color: "#64748b" }}>
                    Phone: {addr.phone} {addr.phone_verified ? "✅ Verified" : "❌ Unverified"}
                  </p>
                  <p style={{ margin: 0, fontSize: "12px", fontFamily: "monospace", color: "#475569", background: "#f1f5f9", padding: "4px 8px", borderRadius: "4px", display: "inline-block" }}>
                    DIGIPIN: {addr.digipin}
                  </p>
                  {!addr.is_default && (
                    <button className="secondary-cta" onClick={() => handleSetDefault(addr.id)} style={{ width: "fit-content", marginTop: "8px" }}>
                      Set as Default
                    </button>
                  )}
                </article>
              ))}
            </>
          ) : (
            <form onSubmit={handleSubmit} className="auth-form" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-recipient" style={{ fontWeight: 600 }}>Recipient Name *</label>
                <input id="address-recipient" value={formData.recipient_name} onChange={(e) => setFormData({ ...formData, recipient_name: e.target.value })} required />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-phone" style={{ fontWeight: 600 }}>Phone Number *</label>
                <div style={{ display: "flex", gap: "8px" }}>
                  <input id="address-phone" value={formData.phone} onChange={(e) => { setFormData({ ...formData, phone: e.target.value }); setPhoneVerified(false); setVerificationSessionId(""); }} placeholder="+919876543210" required style={{ flex: 1 }} />
                  {phoneVerified ? (
                    <span style={{ display: "flex", alignItems: "center", gap: "4px", color: "#16a34a", fontWeight: "bold", fontSize: "14px" }}>Verified</span>
                  ) : (
                    <button type="button" className="secondary-cta" onClick={triggerOtp} disabled={busy || !formData.phone}>Verify via OTP</button>
                  )}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontWeight: 600 }}>Choose Delivery Location on Map *</label>
                <p style={{ fontSize: "12px", margin: "0 0 4px", color: "#64748b" }}>Drag the pin to your exact rooftop. Coordinates will generate the postal DIGIPIN.</p>
                <button type="button" className="secondary-cta" onClick={useCurrentLocation} disabled={busy}><MapPin size={15} /> Use Current Location</button>
                <div ref={mapRef} style={{ height: "200px", borderRadius: "8px", border: "1px solid var(--border)", position: "relative" }}></div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px", color: "#475569", background: "#f8fafc", padding: "6px 12px", borderRadius: "4px" }}>
                  <span>Lat: {coords.latitude.toFixed(6)}, Lng: {coords.longitude.toFixed(6)}</span>
                  <button type="button" className="secondary-cta compact" onClick={handleGeocode} disabled={busy} style={{ fontSize: "11px", padding: "2px 8px" }}>Autofill address fields</button>
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-line-1" style={{ fontWeight: 600 }}>Address Line 1 *</label>
                <input id="address-line-1" value={formData.address_line1} onChange={(e) => setFormData({ ...formData, address_line1: e.target.value })} required />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-line-2" style={{ fontWeight: 600 }}>Address Line 2 (Optional)</label>
                <input id="address-line-2" value={formData.address_line2} onChange={(e) => setFormData({ ...formData, address_line2: e.target.value })} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-locality" style={{ fontWeight: 600 }}>Locality (Optional)</label>
                <input id="address-locality" value={formData.locality} onChange={(e) => setFormData({ ...formData, locality: e.target.value })} />
              </div>
              <div style={{ display: "flex", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-city" style={{ fontWeight: 600 }}>City *</label>
                  <input id="address-city" value={formData.city} onChange={(e) => setFormData({ ...formData, city: e.target.value })} required />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-district" style={{ fontWeight: 600 }}>District *</label>
                  <input id="address-district" value={formData.district} onChange={(e) => setFormData({ ...formData, district: e.target.value })} required />
                </div>
              </div>
              <button type="button" className="secondary-cta wide" onClick={handleManualGeocode} disabled={busy}>Locate this manually entered address on the map</button>
              <div style={{ display: "flex", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-state" style={{ fontWeight: 600 }}>State *</label>
                  <input id="address-state" value={formData.state} onChange={(e) => setFormData({ ...formData, state: e.target.value })} required />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-pin" style={{ fontWeight: 600 }}>Postal PIN *</label>
                  <input id="address-pin" value={formData.postal_pin} onChange={(e) => setFormData({ ...formData, postal_pin: e.target.value })} maxLength={6} required />
                </div>
              </div>
              <div style={{ display: "flex", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label style={{ fontWeight: 600 }}>Address Type</label>
                  <select value={formData.address_type} onChange={(e) => setFormData({ ...formData, address_type: e.target.value })} style={{ height: "42px", padding: "0 12px" }}>
                    <option value="Home">Home</option>
                    <option value="Work">Work</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flex: 1, height: "42px", marginTop: "24px" }}>
                  <input type="checkbox" id="is_default" checked={formData.is_default} onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })} style={{ width: "18px", height: "18px" }} />
                  <label htmlFor="is_default" style={{ fontWeight: 600, cursor: "pointer" }}>Set as default</label>
                </div>
              </div>
              <div style={{ display: "flex", gap: "12px", marginTop: "16px" }}>
                <button type="button" className="secondary-cta wide" onClick={() => setMode("list")} disabled={busy}>Cancel</button>
                <button type="submit" className="primary-cta wide" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : "Save Address"}</button>
              </div>
            </form>
          )}
        </div>

        {showOtpModal && (
          <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", background: "rgba(0,0,0,0.5)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
            <div style={{ background: "white", padding: "24px", borderRadius: "12px", width: "100%", maxWidth: "380px", display: "flex", flexDirection: "column", gap: "16px", boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 style={{ margin: 0 }}>Phone Verification</h3>
                <button type="button" onClick={() => setShowOtpModal(false)} style={{ background: "none", border: "none", cursor: "pointer" }}><X size={20} /></button>
              </div>
              <p style={{ margin: 0, color: "#64748b", fontSize: "14px" }}>Enter the 6-digit verification code sent to <strong>{formData.phone}</strong>.</p>
              <input value={otpCode} onChange={(e) => setOtpCode(e.target.value)} maxLength={6} placeholder="123456" style={{ letterSpacing: "8px", textAlign: "center", fontSize: "24px", padding: "8px" }} />
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                {cooldown > 0 ? <span style={{ color: "#94a3b8" }}>Resend OTP in {cooldown}s</span> : <button type="button" onClick={triggerOtp} style={{ background: "none", border: "none", color: "var(--accent, #e5484d)", cursor: "pointer", padding: 0 }}>Resend OTP</button>}
              </div>
              <button type="button" className="primary-cta wide" onClick={handleVerifyOtp} disabled={busy || otpCode.length < 6}>Verify Code</button>
            </div>
          </div>
        )}
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

export default function Storefront({ initialProductId = null }) {
  const router = useRouter();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [visibleCount, setVisibleCount] = useState(50);
  const [selected, setSelected] = useState(null);
  const [similarProducts, setSimilarProducts] = useState([]);
  const [drawer, setDrawer] = useState(null);
  const [cart, setCart] = useState([]);
  const [cartBusy, setCartBusy] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [checkoutStep, setCheckoutStep] = useState("address");
  const [lastOrderId, setLastOrderId] = useState(null);
  const [lastOrderSummary, setLastOrderSummary] = useState(null);
  const [voiceAudioKey, setVoiceAudioKey] = useState(null);
  const [agentAnswer, setAgentAnswer] = useState("");
  const [sizeSaathi, setSizeSaathi] = useState(null);
  const [reviewSummary, setReviewSummary] = useState(null);
  const [trust, setTrust] = useState({ open: false, results: {}, message: "" });
  const [auth, setAuth] = useState(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [pendingAfterAuth, setPendingAfterAuth] = useState(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [wishlist, setWishlist] = useState([]);
  const [orders, setOrders] = useState([]);
  const [returns, setReturns] = useState([]);
  const [addresses, setAddresses] = useState([]);
  const [selectedReturnId, setSelectedReturnId] = useState(null);

  useEffect(() => {
    // Restoring the browser session is intentionally client-only; the server render
    // always starts logged out to avoid a hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    Promise.all([
      request("/storefront/products"),
      initialProductId ? request(`/storefront/products/${initialProductId}`) : Promise.resolve(null),
    ])
      .then(([catalogue, detail]) => { setProducts(catalogue.items); setCategories(["All", ...catalogue.categories]); if (detail) setSelected(detail); })
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [initialProductId]);

  useEffect(() => {
    if (!selected?.id) {
      return;
    }
    let active = true;
    request(`/storefront/products/${selected.id}/similar`)
      .then((payload) => { if (active) setSimilarProducts(payload.items || []); })
      .catch(() => { if (active) setSimilarProducts([]); });
    return () => { active = false; };
  }, [selected?.id]);

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

  async function refreshAccountData() {
    if (!auth?.user || auth.user.role !== "buyer") {
      setWishlist([]); setOrders([]); setReturns([]); setAddresses([]);
      return;
    }
    const [wishlistData, orderData, returnData, addressData] = await Promise.all([
      getWishlist(),
      listMyOrders(),
      listMyReturns(),
      get("/addresses")
    ]);
    setWishlist(wishlistData.items);
    setOrders(orderData);
    setReturns(returnData);
    setAddresses(addressData);
  }

  useEffect(() => {
    if (auth?.user?.role !== "buyer") return undefined;
    let active = true;
    Promise.all([getWishlist(), listMyOrders(), listMyReturns(), get("/addresses")])
      .then(([wishlistData, orderData, returnData, addressData]) => {
        if (!active) return;
        setWishlist(wishlistData.items);
        setOrders(orderData);
        setReturns(returnData);
        setAddresses(addressData);
      })
      .catch((reason) => { if (active) setToast(reason.message); });
    return () => { active = false; };
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
    setAccountMenuOpen(false);
  }

  function toggleWishlist(product) {
    requireAuth(async () => {
      try {
        const wished = wishlist.some((item) => item.product.id === product.id);
        if (wished) await removeWishlist(product.id); else await addWishlist(product.id);
        await refreshAccountData();
        setToast(wished ? "Removed from wishlist" : "Saved to wishlist");
      } catch (reason) { setToast(reason.message || "Could not update wishlist"); }
    });
  }

  async function submitFitFeedback(orderId, feedback) {
    try {
      await post(`/orders/${orderId}/fit-feedback`, { feedback });
      await refreshAccountData();
      setToast("Thanks! Size Saathi will use this for future recommendations.");
    } catch (reason) { setToast(reason.message || "Could not save fit feedback"); }
  }

  async function startReturn(orderId, productId, returnType = "refund") {
    const reason = window.prompt(`Why are you ${returnType === "exchange" ? "exchanging" : "returning"} this product?`);
    if (!reason) return;
    try {
      const res = await createReturnRequest(orderId, productId, reason, returnType);
      await refreshAccountData();
      setSelectedReturnId(res.id);
      setDrawer("return-verify");
      setToast(`${returnType === "exchange" ? "Exchange" : "Return"} request created. Add evidence for Agent 8 review.`);
    } catch (reasonError) { setToast(reasonError.message || "Could not create return"); }
  }

  async function startReview(productId, orderId) {
    const rating = Number(window.prompt("Rate this delivered product from 1 to 5:", "5"));
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
      setToast("Please enter a whole-number rating from 1 to 5");
      return;
    }
    const text = window.prompt("Write your review:", "");
    if (text === null) return;
    try {
      await createReview({ product_id: productId, order_id: orderId, rating, text });
      await refreshAccountData();
      setToast("Review posted — Agent 4 is checking it in the background");
    } catch (reason) {
      setToast(reason.message || "Could not post this review");
    }
  }

  function handleViewReturn(returnId) {
    setSelectedReturnId(returnId);
    setDrawer("return-verify");
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

  function openProduct(product) {
    // Agents 1 (catalogue image generation) and 2 (spec extraction) run once, at
    // listing-creation time in the seller portal -- not on every buyer view. Now that
    // they call real models (SAM 2.0 / Nano Banana 2 / Stable Diffusion / Claude),
    // re-running them per page view would mean a real multi-minute wait on every
    // product click. Judges can watch the real pipeline via "Watch all 8 agents".
    router.push(`/products/${product.id}`);
  }

  function addToCart(product, size) {
    const hasChart = product.size_chart && Object.keys(product.size_chart).length > 0;
    const resolvedSize = size || (hasChart ? Object.keys(product.size_chart)[0] : "Standard");
    if (hasChart && !size) {
      setToast("Please select a size first");
      router.push(`/products/${product.id}`);
      return;
    }
    requireAuth(async () => {
      const variantId = variantIdFor(product, resolvedSize);
      setCartBusy(variantId);
      try {
        const response = await apiAddToCart(variantId);
        setCart(response.items);
        setToast(`${product.name} added to cart`);
      } catch (reason) {
        setToast(reason.message || "Could not add this to your cart");
      } finally {
        setCartBusy(null);
      }
    });
  }

  async function updateCartQuantity(item, qty) {
    if (cartBusy) return;
    setCartBusy(item.id);
    try {
      const response = await updateCartItem(item.id, qty);
      setCart(response.items);
      setToast(qty === 0 ? `${item.product_name} removed from cart` : `Quantity updated to ${qty}`);
    } catch (reason) {
      setToast(reason.message || "Could not update this quantity");
    } finally {
      setCartBusy(null);
    }
  }

  async function removeFromCart(item) {
    if (cartBusy) return;
    setCartBusy(item.id);
    try {
      const response = await removeCartItem(item.id);
      setCart(response.items);
      setToast(`${item.product_name} removed from cart`);
    } catch (reason) {
      setToast(reason.message || "Could not remove this item");
    } finally {
      setCartBusy(null);
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
      const address = addresses.find((item) => item.is_default) || addresses[0];
      if (!address) {
        setDrawer("addresses");
        return;
      }
      const rawAddr = [address.address_line1, address.address_line2, address.locality, address.city]
        .filter(Boolean)
        .join(", ");
      const pin = address.postal_pin;
      const coords = { latitude: address.latitude, longitude: address.longitude };
      try {
        const payload = await execute("Agent 6 is checking coordinates, PIN and DIGIPIN…", () => postAndPoll("/address/verify", { buyer_id: buyerId, raw_address: rawAddr, postal_pin: pin, coordinates: coords }));
        setToast(payload.results.address_guardian?.summary || "Address verified");
      } catch { /* execute() already shows a toast on error */ }
    });
  }

  async function confirmOrder(addressId) {
    setBusy(true);
    try {
      const order = await createOrder(addressId, "cod");
      setLastOrderId(order.order_id);
      setLastOrderSummary({ amount: order.total_amount, paymentMode: "cod", address: addresses.find((item) => item.id === addressId) });
      setToast(
        order.delivery_confirmation_queued
          ? "Order placed — Agent 7 delivery verification is queued"
          : "Order placed, but delivery verification could not be queued"
      );
      await refreshCart();
      await refreshAccountData();
      setCheckoutStep("done");
    } catch (reason) {
      setToast(reason.message || "Could not place this order");
    } finally {
      setBusy(false);
    }
  }

  async function confirmOrderPrepaid(addressId) {
    setBusy(true);
    try {
      const orderData = await createOrder(addressId, "prepaid");
      if (!window.Razorpay) {
        await new Promise((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "https://checkout.razorpay.com/v1/checkout.js";
          script.async = true;
          script.onload = resolve;
          script.onerror = reject;
          document.body.appendChild(script);
        });
      }

      const selectedAddress = addresses.find((a) => a.id === addressId);

      const options = {
        key: orderData.razorpay.key_id,
        amount: orderData.razorpay.amount,
        currency: orderData.razorpay.currency,
        name: "Kavach Saathi Store",
        description: "Secure Checkout Payment",
        order_id: orderData.razorpay.razorpay_order_id,
        handler: async function (response) {
          try {
            setBusy(true);
            const payment = await post(`/orders/${orderData.order_id}/verify-payment`, {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            setLastOrderId(orderData.order_id);
            setLastOrderSummary({ amount: orderData.total_amount, paymentMode: "prepaid", address: selectedAddress });
            setToast(
              payment.delivery_confirmation_queued
                ? "Payment verified — Agent 7 delivery verification is queued"
                : "Payment verified, but delivery verification could not be queued"
            );

            await refreshCart();
            await refreshAccountData();
            setCheckoutStep("done");
          } catch (err) {
            setToast("Payment verification failed: " + err.message);
          } finally {
             setBusy(false);
          }
        },
        prefill: {
          name: auth?.user?.name,
          contact: selectedAddress?.phone || ""
        },
        theme: {
          color: "#e5484d"
        },
        modal: {
          ondismiss: () => setToast("Payment was cancelled. Your cart is unchanged; you can retry checkout."),
        },
      };
      const rzp = new window.Razorpay(options);
      rzp.on("payment.failed", (response) => {
        setToast(response.error?.description || "Payment failed. Your cart is unchanged; please retry.");
      });
      rzp.open();
    } catch (reason) {
      setToast(reason.message || "Prepaid checkout failed");
    } finally {
      setBusy(false);
    }
  }

  if (initialProductId) {
    if (loading) return <div className="product-page-loading"><LoaderCircle className="spin" size={28} /><p>Loading verified product details…</p></div>;
    if (error || !selected) return <div className="product-page-loading"><ShieldCheck size={30} /><h1>Product unavailable</h1><p>{error || "This product could not be found."}</p><button className="primary-cta" type="button" onClick={() => router.push("/")}>Return to storefront</button></div>;
    return (
      <>
        <ProductPageView
          product={selected}
          similarProducts={similarProducts}
          busy={busy}
          cart={cart}
          cartBusy={cartBusy}
          onBack={() => router.back()}
          onClose={() => router.push("/")}
          onAdd={addToCart}
          onUpdateCart={updateCartQuantity}
          onOpenCart={() => setDrawer("cart")}
          onWishlist={toggleWishlist}
          wished={wishlist.some((item) => item.product.id === selected.id)}
          onSize={recommendSize}
          onReview={checkReview}
          onAsk={askQuestion}
          onAskVoice={askVoice}
          voiceAudioUrl={audioUrl(voiceAudioKey)}
          agentAnswer={agentAnswer}
          sizeSaathi={sizeSaathi ? { ...sizeSaathi, audioUrl: audioUrl(sizeSaathi.audioKey) } : null}
        />
        <CartDrawer items={cart} open={drawer === "cart"} busyItem={cartBusy} onClose={() => setDrawer(null)} onUpdate={updateCartQuantity} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); })} />
        <CheckoutDrawer open={drawer === "checkout"} busy={busy} step={checkoutStep} orderId={lastOrderId} orderSummary={lastOrderSummary} onClose={() => setDrawer(null)} onGoOrders={() => setDrawer("orders")} onConfirm={confirmOrder} onConfirmPrepaid={confirmOrderPrepaid} addresses={addresses} onManageAddresses={() => setDrawer("addresses")} buyerName={auth?.user?.name} />
        <AddressManagerDrawer open={drawer === "addresses"} onClose={() => { setDrawer(null); refreshAccountData(); }} buyerId={auth?.user?.id} />
        <AccountDataDrawer type={drawer} open={["orders", "wishlist", "returns"].includes(drawer)} orders={orders} wishlist={wishlist} returns={returns} onClose={() => setDrawer(null)} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} />
        <ReturnVerificationDrawer open={drawer === "return-verify"} returnId={selectedReturnId} returns={returns} orders={orders} onClose={() => { setDrawer(null); refreshAccountData(); }} onRefreshData={refreshAccountData} />
        <TrustDock trust={trust} busy={busy} onClose={() => setTrust((current) => ({ ...current, open: false }))} />
        <AuthModal open={authModalOpen} onClose={() => { setAuthModalOpen(false); setPendingAfterAuth(null); }} onAuthenticated={handleAuthenticated} />
        <ReviewSummaryDialog data={reviewSummary} onClose={() => setReviewSummary(null)} />
        {toast && <div className="toast" role="status" aria-live="polite"><Check size={16} /> {toast}</div>}
      </>
    );
  }

  return (
    <div className="storefront">
      <header className="site-header">
        <div className="header-main">
          <button className="mobile-menu" type="button" onClick={() => setMobileNavOpen((open) => !open)} aria-label={mobileNavOpen ? "Close menu" : "Open menu"} aria-expanded={mobileNavOpen}><Menu /></button>
          <a className="logo" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a>
          <label className="search-box"><Search size={19} /><input value={search} onChange={(event) => { setSearch(event.target.value); setVisibleCount(50); }} placeholder="Try Saree, Kurti or Search by Product Code" /><kbd>⌘ K</kbd></label>
          <nav className={`utility-nav ${mobileNavOpen ? "open" : ""}`} aria-label="Account navigation">
            <button type="button" onClick={() => router.push("/support")}><Headphones size={19} /><span>Support</span></button>
            {auth?.user ? (
              <>
                <label className="language-picker">
                  <select value={auth.user.preferred_language} onChange={(event) => changeLanguage(event.target.value)} aria-label="Preferred language">
                    {LANGUAGE_OPTIONS.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
                  </select>
                </label>
                <div className="account-menu"><button type="button" onClick={() => setAccountMenuOpen((open) => !open)} aria-expanded={accountMenuOpen} title={auth.user.email || auth.user.phone}><CircleUserRound size={19} /><span>{auth.user.name}</span><ChevronDown size={14} /></button>{accountMenuOpen && <div className="account-dropdown">
                  <button type="button" onClick={() => { setDrawer("orders"); setAccountMenuOpen(false); }}><Package size={14} /> My Orders <small>{orders.length}</small></button>
                  <button type="button" onClick={() => { setDrawer("cart"); setAccountMenuOpen(false); }}><ShoppingCart size={14} /> My Cart <small>{cart.reduce((sum, item) => sum + item.qty, 0)}</small></button>
                  <button type="button" onClick={() => { setDrawer("wishlist"); setAccountMenuOpen(false); }}><Heart size={14} /> My Wishlist <small>{wishlist.length}</small></button>
                  <button type="button" onClick={() => { setDrawer("returns"); setAccountMenuOpen(false); }}><RotateCcw size={14} /> My Returns <small>{returns.length}</small></button>
                  <button type="button" onClick={() => { setDrawer("addresses"); setAccountMenuOpen(false); }}><MapPin size={14} /> My Addresses</button>
                  <button type="button" onClick={() => { handleLogout(); setMobileNavOpen(false); }}><LogOut size={14} /> Logout</button>
                </div>}</div>
              </>
            ) : (
              <button type="button" onClick={() => { setAuthModalOpen(true); setMobileNavOpen(false); }}><CircleUserRound size={19} /><span>Login</span></button>
            )}
            <button type="button" onClick={() => { setDrawer("cart"); setMobileNavOpen(false); }}><ShoppingCart size={19} /><span>Cart</span>{cart.length > 0 && <b>{cart.reduce((sum, item) => sum + item.qty, 0)}</b>}</button>
          </nav>
        </div>
        <div className="category-nav" aria-label="Product categories">{categories.map((item) => <button className={category === item ? "active" : ""} type="button" key={item} onClick={() => { setCategory(item); setVisibleCount(50); }}>{item}<small>{item === "All" ? products.length : categoryCounts[item] || 0}</small></button>)}</div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy"><p><ShieldCheck size={14} /> AGENT-PROTECTED SHOPPING</p><h1>Smart shopping.<br /><em>Safer at every step.</em></h1><span>Discover value-first products while eight Kavach Saathi agents verify listings, sizes, reviews, delivery and returns.</span><div><button className="hero-primary" type="button" onClick={() => document.querySelector("#products")?.scrollIntoView({ behavior: "smooth" })}>Shop protected deals <ArrowRight size={18} /></button><button className="hero-secondary" type="button" onClick={() => setTrust((current) => ({ ...current, open: true }))}><Sparkles size={17} /> View agent activity</button></div><small><Check size={13} /> Persistent evidence <Check size={13} /> Grounded AI <Check size={13} /> Fair return policy</small></div>
          <div className="hero-visual"><div className="hero-product"><img src="/mock-assets/products/P-001.png" alt="Maroon hand-block kurta" /><span className="floating-check one"><Camera size={16} /><b>Image truth</b><small>Agent 1 passed</small></span><span className="floating-check two"><Sparkles size={16} /><b>Size XL</b><small>94% evidence</small></span><span className="floating-check three"><ShieldCheck size={16} /><b>Return fair</b><small>No auto-reject</small></span></div></div>
        </section>

        <section className="trust-ribbon">
          <div><span><Camera /></span><p><strong>Authentic listings</strong><small>Copied photos detected</small></p></div>
          <div><span><Sparkles /></span><p><strong>Size that travels</strong><small>Across every seller chart</small></p></div>
          <div><span><MessageCircle /></span><p><strong>Review truth</strong><small>Text stays, fake media hides</small></p></div>
          <div><span><MapPin /></span><p><strong>Address confidence</strong><small>Coordinates + DIGIPIN</small></p></div>
          <div><span><RotateCcw /></span><p><strong>Fair returns</strong><small>Evidence before decisions</small></p></div>
        </section>

        <section className="catalogue-proof" aria-label="Catalogue data summary">
          <div><strong>{products.length || 500}</strong><span>Detailed products</span></div>
          <div><strong>50</strong><span>Products in every category</span></div>
          <div><strong>{Math.max(categories.length - 1, 10)}</strong><span>Marketplace categories</span></div>
          <div><strong>1,000</strong><span>Review evidence records</span></div>
          <div><strong>8</strong><span>Orchestrated safety agents</span></div>
        </section>

        <section className="catalogue" id="products">
          <div className="section-heading"><div><p>{category === "All" ? "ALL 10 CATEGORIES REPRESENTED" : category.toUpperCase()}</p><h2>Products worth discovering</h2></div><span>Showing {displayedProducts.length} of {visibleProducts.length} products · {category === "All" ? "50 available in every category" : "Full category catalogue"}</span></div>
          {error && <div className="error-state"><ShieldCheck /><p><strong>Storefront API is unavailable.</strong>{error}</p></div>}
          {loading ? <div className="loading-grid">{Array.from({ length: 10 }, (_, index) => <div key={index}></div>)}</div> : <><div className="product-grid">{displayedProducts.map((product) => <ProductCard key={product.id} product={product} onOpen={openProduct} onAdd={addToCart} onWishlist={toggleWishlist} wished={wishlist.some((item) => item.product.id === product.id)} pending={cartBusy === variantIdFor(product, "Standard")} />)}</div>{displayedProducts.length < visibleProducts.length && <button className="load-more" type="button" onClick={() => setVisibleCount((count) => count + 50)}>Load 50 more products <ChevronRight size={16} /></button>}</>}
        </section>

        <section className="safety-story">
          <div><p>ONE ORCHESTRATOR</p><h2>Protection follows the order,<br />not a separate dashboard.</h2></div>
          <div className="story-steps">{Object.entries(AGENTS).map(([key, agent]) => { const Icon = agent.icon; return <button type="button" key={key} onClick={() => setTrust((current) => ({ ...current, open: true }))}><span>{agent.number}</span><Icon size={19} /><strong>{agent.short}</strong><ChevronRight size={15} /></button>; })}</div>
        </section>
      </main>

      <footer className="site-footer"><a className="logo inverse" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a><p>Agent-protected commerce with persistent evidence and auditable decisions.</p><div><button type="button" onClick={() => setTrust((current) => ({ ...current, open: true }))}>Agent activity</button><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API docs</a></div></footer>

      <button className="floating-saathi" type="button" onClick={() => setTrust((current) => ({ ...current, open: !current.open }))}><ShieldCheck size={20} /><span><strong>Kavach Saathi</strong><small>{busy ? "Agents working…" : `${Object.keys(trust.results).length}/8 checks visible`}</small></span></button>
      <TrustDock trust={trust} busy={busy} onClose={() => setTrust((current) => ({ ...current, open: false }))} />
      <CartDrawer items={cart} open={drawer === "cart"} busyItem={cartBusy} onClose={() => setDrawer(null)} onUpdate={updateCartQuantity} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); })} />
      <CheckoutDrawer open={drawer === "checkout"} busy={busy} step={checkoutStep} orderId={lastOrderId} orderSummary={lastOrderSummary} onClose={() => setDrawer(null)} onGoOrders={() => setDrawer("orders")} onConfirm={confirmOrder} onConfirmPrepaid={confirmOrderPrepaid} addresses={addresses} onManageAddresses={() => setDrawer("addresses")} buyerName={auth?.user?.name} />
      <AddressManagerDrawer open={drawer === "addresses"} onClose={() => { setDrawer(null); refreshAccountData(); }} buyerId={auth?.user?.id} />
      <AccountDataDrawer type={drawer} open={["orders", "wishlist", "returns"].includes(drawer)} orders={orders} wishlist={wishlist} returns={returns} onClose={() => setDrawer(null)} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} />
      <ReturnVerificationDrawer open={drawer === "return-verify"} returnId={selectedReturnId} returns={returns} orders={orders} onClose={() => { setDrawer(null); refreshAccountData(); }} onRefreshData={refreshAccountData} />
      <AuthModal open={authModalOpen} onClose={() => { setAuthModalOpen(false); setPendingAfterAuth(null); }} onAuthenticated={handleAuthenticated} />
      <ReviewSummaryDialog data={reviewSummary} onClose={() => setReviewSummary(null)} />
      {toast && <div className="toast" role="status" aria-live="polite"><Check size={16} /> {toast}</div>}
    </div>
  );
}
