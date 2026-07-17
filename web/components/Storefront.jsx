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
import { useRouter, usePathname } from "next/navigation";
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
        <span className="agent-checked"><ShieldCheck size={13} /> Verified</span>
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

function VishwasSamvadChat({ auth, onClose, initialMessage = "", initialProduct = null, initialPrompts = [] }) {
  const pathname = usePathname();
  const [conversation, setConversation] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState(initialMessage);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef(null);
  const voiceStreamRef = useRef(null);
  const voiceChunksRef = useRef([]);

  const pageType = pathname?.startsWith("/products/") ? "product"
    : pathname?.startsWith("/account/orders") ? "orders"
      : pathname?.startsWith("/account/returns") ? "returns"
        : pathname?.startsWith("/account/addresses") ? "addresses"
          : pathname?.startsWith("/account/cart") ? "cart"
            : pathname?.startsWith("/account/wishlist") ? "wishlist"
              : pathname?.startsWith("/support") ? "support" : "home";

  async function refreshConversation(preferred = null) {
    const recent = await get("/chat/conversations");
    setConversations(recent);
    const current = preferred || recent.find((item) => item.status === "active");
    if (!current) return;
    setConversation(current);
    setMessages(await get(`/chat/conversations/${current.id}/messages`));
  }

  useEffect(() => {
    if (!auth?.user || auth.user.role !== "buyer") return;
    let active = true;
    post("/chat/conversations", {
      page_route: pathname || "/",
      page_type: pageType,
      product_id: initialProduct?.id || null,
    }).then(async (created) => {
      if (!active) return;
      setConversation(created);
      const [history, recent] = await Promise.all([
        get(`/chat/conversations/${created.id}/messages`),
        get("/chat/conversations"),
      ]);
      if (active) { setMessages(history); setConversations(recent); }
    }).catch((reason) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [auth?.user, initialProduct?.id, pageType, pathname]);

  async function submitMessage({ content = "", audioKey = null }) {
    if ((!content && !audioKey) || !conversation || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await post("/chat/messages", {
        conversation_id: conversation.id,
        text: content,
        audio_key: audioKey,
        language: "auto",
        idempotency_key: crypto.randomUUID(),
      });
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
      setText("");
    } catch (reason) {
      setError(reason.message || "The answer could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage(event) {
    event?.preventDefault();
    await submitMessage({ content: text.trim() });
  }

  async function startVoiceQuestion() {
    if (busy || recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      voiceStreamRef.current = stream;
      recorderRef.current = recorder;
      voiceChunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data.size) voiceChunksRef.current.push(event.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        voiceStreamRef.current = null;
        setRecording(false);
        const blob = new Blob(voiceChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        try {
          setBusy(true);
          const presign = await post("/uploads/presign", { kind: "voice", filename: "vishwas-question.webm", content_type: blob.type || "audio/webm" });
          const uploaded = await fetch(presign.upload_url, { method: "PUT", body: blob, headers: { "Content-Type": blob.type || "audio/webm" } });
          if (!uploaded.ok) throw new Error("Voice upload failed.");
          setBusy(false);
          await submitMessage({ audioKey: presign.object_key });
        } catch (reason) {
          setBusy(false);
          setError(reason.message || "The voice question could not be processed.");
        }
      };
      recorder.start();
      setRecording(true);
    } catch (reason) {
      setError(reason.message || "Microphone access was not granted.");
    }
  }

  function stopVoiceQuestion() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  async function startNewConversation() {
    setBusy(true);
    setError("");
    try {
      if (conversation?.status === "active") {
        await post(`/chat/conversations/${conversation.id}/archive`, {});
      }
      const created = await post("/chat/conversations", {
        page_route: pathname || "/",
        page_type: pageType,
        product_id: initialProduct?.id || null,
      });
      setMessages([]);
      setText(initialMessage);
      await refreshConversation(created);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  if (!auth?.user || auth.user.role !== "buyer") {
    return <div className="vishwas-samvad-empty"><strong>Vishwas Saathi</strong><p>Log in with a buyer account to continue the conversation.</p><button type="button" onClick={onClose}>Close</button></div>;
  }

  return (
    <section aria-label="Vishwas Saathi chat" className="vishwas-samvad-chat">
      <header className="vishwas-samvad-header"><div><strong>Vishwas Saathi</strong><small>Ask about this page, product, order, return, or shopping journey.</small></div><div className="vishwas-samvad-header-actions"><button type="button" onClick={startNewConversation} disabled={busy}>New conversation</button><button type="button" onClick={onClose} aria-label="Close chat"><X size={18} /></button></div></header>
      {conversations.length > 1 && <label className="vishwas-conversation-picker">Recent conversations<select value={conversation?.id || ""} onChange={(event) => refreshConversation(conversations.find((item) => item.id === event.target.value))}>{conversations.map((item) => <option value={item.id} key={item.id}>{new Date(item.created_at).toLocaleString("en-IN")} · {item.status}</option>)}</select></label>}
      <div className="vishwas-samvad-messages-container" aria-live="polite">
        {!messages.length && <div className="vishwas-samvad-empty"><MessageCircle size={24} /><p>I answer only from evidence in your authorized page and records.</p></div>}
        {messages.map((message) => { const answerAudio = message.sender === "assistant" ? message.metadata_json?.data?.audio_key : null; return <div className={`vishwas-message ${message.sender}`} key={message.id}><span>{message.content}</span>{answerAudio && <audio controls preload="none" src={audioUrl(answerAudio)}>Your browser does not support audio playback.</audio>}</div>; })}
        {busy && <div className="vishwas-message assistant"><LoaderCircle className="spin" size={16} /> Checking the evidence…</div>}
      </div>
      {!messages.length && !!initialPrompts.length && <div className="vishwas-prompts" aria-label="Suggested questions">{initialPrompts.map((prompt) => <button type="button" key={prompt} onClick={() => setText(prompt)}>{prompt}</button>)}</div>}
      {error && <p className="field-error">{error}</p>}
      <form className="vishwas-samvad-input-area" onSubmit={sendMessage}><input value={text} onChange={(event) => setText(event.target.value)} placeholder="Type your question…" aria-label="Vishwas Saathi message" /><button type="button" className="secondary-cta compact" onClick={recording ? stopVoiceQuestion : startVoiceQuestion} disabled={busy} aria-label={recording ? "Stop recording" : "Record a voice question"}>{recording ? "Stop" : <Mic size={16} />}</button><button className="vishwas-samvad-send-btn" type="submit" disabled={busy || !text.trim()}>Send</button></form>
    </section>
  );
}

function ProductPageView({ product, similarProducts, busy, cart, cartBusy, onBack, onClose, onAdd, onUpdateCart, onOpenCart, onWishlist, wished, onSize, onReview, sizeSaathi, onOpenVishwasSamvad }) {
  const [size, setSize] = useState("");

  useEffect(() => {
    // Size Saathi arrives asynchronously from the agent run and becomes the
    // initial selection; buyers can still override it afterward.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (sizeSaathi?.size) setSize(sizeSaathi.size);
  }, [sizeSaathi?.size]);


  const sizes = useMemo(() => Object.keys(product?.size_chart || {}), [product]);
  if (!product) return null;
  const selectedSize = sizes.length ? (sizes.includes(size) ? size : null) : "Standard";
  const variantId = selectedSize ? variantIdFor(product, selectedSize) : null;
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
          <span><ShieldCheck size={15} /> Verified listing</span>
        </div>
        <div className="drawer-content">
          <p className="drawer-category">{product.category}</p>
          <h2>{product.name}</h2>
          <p className="drawer-seller"><BadgeCheck size={14} /> {product.brand} · {product.seller.name} · {product.seller.city}</p>
          <div className="drawer-price"><strong>{money(product.price)}</strong><s>{money(product.original_price)}</s><span>{product.discount_percent}% off</span></div>
          {product.description && <p className="drawer-description">{product.description}</p>}
          {!!product.badges?.length && <div className="product-badges">{product.badges.map((badge) => <span key={badge}><Check size={11} /> {badge}</span>)}</div>}
          <div className="trust-banner"><ShieldCheck size={19} /><div><strong>Verified product details</strong><p>Catalogue imagery and specifications matched to verified label details.</p></div></div>

          {!!sizes.length && <div className="size-section"><div className="section-label"><strong>Select size</strong><button type="button" onClick={onSize} disabled={busy}>{busy ? <LoaderCircle className="spin" size={13} /> : <Sparkles size={13} />} Ask Size Saathi</button></div><div className="size-row">{sizes.map((item) => <button className={selectedSize === item ? "selected" : ""} type="button" key={item} onClick={() => setSize(item)}>{item}</button>)}</div>{!selectedSize && <small>Choose a size, or ask Size Saathi for evidence-based guidance. No size is preselected.</small>}{sizeSaathi && <div className="agent-answer size-saathi-answer">{sizeSaathi.size ? <strong>{sizeSaathi.source === "product_popularity" ? "Popular-size fallback" : "Size Saathi recommendation"}: {sizeSaathi.size}</strong> : <strong>More information needed</strong>}{sizeSaathi.message && <span>{sizeSaathi.message}</span>}</div>}</div>}

          <section className="trust-banner" aria-label="Vishwas Saathi">
            <MessageCircle size={19} />
            <div><strong>Vishwas Saathi</strong><p>Ask about this product, sizing, or your shopping journey.</p></div>
            <button type="button" className="secondary-cta compact" onClick={() => onOpenVishwasSamvad(product)}>Ask</button>
          </section>

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
              <button
                className="primary-cta"
                type="button"
                onClick={() => selectedSize && onAdd(product, selectedSize)}
                disabled={!selectedSize || (variantId !== null && cartBusy === variantId)}
                aria-busy={variantId !== null && cartBusy === variantId}
              >
                {variantId !== null && cartBusy === variantId ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <ShoppingBag size={16} />
                )}
                {!selectedSize ? "Select a size" : variantId !== null && cartBusy === variantId ? "Adding…" : "Add to cart"}
              </button>
            )}
          </div>



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
                    (Auto-verified review content)
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
                        <ShieldAlert size={12} /> Photo hidden — incorrect product matched
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
        <p>Every product, review, and return is verified for authenticity.</p>
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
          <div><p>VERIFIED REVIEWS</p><h2>Review summary</h2></div>
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

function CartDrawer({ items, open, busyItem, onClose, onUpdate, onRemove, onCheckout, fullScreen = false }) {
  const total = items.reduce((sum, item) => sum + item.line_total, 0);

  const drawerContent = (
    <aside className={fullScreen ? "full-screen-account-page" : "side-drawer cart-drawer"} role="dialog" aria-modal="true" aria-label="Shopping cart" style={fullScreen ? { width: "100%", background: "white", padding: "24px", borderRadius: "12px", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.05)", position: "relative" } : {}}>
      {fullScreen && (
        <button type="button" onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", color: "var(--muted)", fontWeight: "600", fontSize: "14px", padding: 0, marginBottom: "20px" }}>
          <ArrowLeft size={16} /> Back to Shop
        </button>
      )}
      <div className="side-heading" style={fullScreen ? { borderBottom: "1px solid var(--line)", paddingBottom: "16px", marginBottom: "20px" } : {}}>
        <div><p>YOUR CART</p><h2>{items.length ? `${items.length} item${items.length > 1 ? "s" : ""}` : "Cart is empty"}</h2></div>
        {!fullScreen && <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>}
      </div>
      <div className="cart-items">
        {!items.length && <div className="cart-empty"><ShoppingBag size={34} /><p>Add something you love. Kavach Saathi will verify it along the way.</p></div>}
        {items.map((item) => <article className="cart-item" key={item.id}><img src={assetUrl(item.image_url)} alt={item.product_name} /><div><strong>{item.product_name}</strong><p>Size {item.size || "Standard"}</p><span>{money(item.line_total)}</span><QuantityStepper compact qty={item.qty} max={Math.min(10, item.stock_qty)} busy={busyItem === item.id} onDecrease={() => onUpdate(item, item.qty - 1)} onIncrease={() => onUpdate(item, item.qty + 1)} /><button type="button" onClick={() => onRemove(item)} disabled={busyItem === item.id}>Remove</button></div><ShieldCheck size={18} /></article>)}
      </div>
      {!!items.length && <div className="cart-total" style={fullScreen ? { marginTop: "24px", paddingTop: "20px", borderTop: "1px solid var(--line)" } : {}}><div><span>Product total</span><strong>{money(total)}</strong></div><div><span>Delivery</span><strong className="free">FREE</strong></div><div className="grand-total"><span>Order total</span><strong>{money(total)}</strong></div><button className="primary-cta wide" type="button" onClick={onCheckout}>Continue to secure checkout <ArrowRight size={17} /></button><p><ShieldCheck size={13} /> Address and delivery consent will be verified before dispatch.</p></div>}
    </aside>
  );

  if (fullScreen) {
    return (
      <div className="account-page-container" style={{ maxWidth: "800px", margin: "40px auto", padding: "0 20px" }}>
        {drawerContent}
      </div>
    );
  }

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close cart" />
      {drawerContent}
    </div>
  );
}

function AccountDataDrawer({ type, open, orders, wishlist, returns, onClose, onOpenProduct, onRemoveWishlist, onStartReturn, onStartReview, onViewReturn, onSubmitFitFeedback, fullScreen = false }) {
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

  function confirmationMessage(order) {
    const state = order.whatsapp_workflow_state;
    if (state === "awaiting_order_confirmation" || state === "ownership_prompt_sent" || order.status === "AWAITING_BUYER_CONFIRMATION") return "Please confirm on WhatsApp that you placed this order.";
    if (state === "awaiting_delivery_date_confirmation") return `Order confirmed. Please confirm the proposed delivery date${order.promised_delivery_date ? ` (${new Date(order.promised_delivery_date).toLocaleDateString("en-IN")})` : ""} on WhatsApp.`;
    if (state === "awaiting_reschedule_choice") return "Choose your preferred rescheduled delivery date on WhatsApp.";
    if (state === "delivery_scheduled" || order.status === "DELIVERY_SCHEDULED") return `Confirmed on WhatsApp. Your order will be delivered${order.promised_delivery_date ? ` by ${new Date(order.promised_delivery_date).toLocaleDateString("en-IN")}` : " soon"}.`;
    if (state === "awaiting_cancellation_confirmation") return "Please confirm on WhatsApp whether you want to keep or cancel this order.";
    return "We will update you as this order moves toward delivery.";
  }

  function orderStatusLabel(order) {
    const state = order.whatsapp_workflow_state;
    if (state === "awaiting_order_confirmation" || state === "ownership_prompt_sent") return "WHATSAPP CONFIRMATION PENDING";
    if (state === "awaiting_delivery_date_confirmation") return "DELIVERY DATE CONFIRMATION PENDING";
    if (state === "awaiting_reschedule_choice") return "RESCHEDULE DATE PENDING";
    if (state === "delivery_scheduled") return "DELIVERY SCHEDULED";
    return (order.status || "PROCESSING").replaceAll("_", " ");
  }

  const drawerContent = (
    <aside className={fullScreen ? "full-screen-account-page" : "side-drawer account-data-drawer"} role="dialog" aria-modal="true" aria-label={title} style={fullScreen ? { width: "100%", background: "white", padding: "24px", borderRadius: "12px", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.05)", position: "relative" } : {}}>
      {fullScreen && (
        <button type="button" onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", color: "var(--muted)", fontWeight: "600", fontSize: "14px", padding: 0, marginBottom: "20px" }}>
          <ArrowLeft size={16} /> Back to Shop
        </button>
      )}
      <div className="side-heading" style={fullScreen ? { borderBottom: "1px solid var(--line)", paddingBottom: "16px", marginBottom: "20px" } : {}}>
        <div><p>YOUR ACCOUNT</p><h2>{title}</h2></div>
        {!fullScreen && <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>}
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
                <span style={{ fontSize: "11px", fontWeight: "600", color: statusColor(order.status), background: "#f8fafc", padding: "2px 8px", borderRadius: "4px" }}>{orderStatusLabel(order)}</span>
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
                        {item.return_info.confidence_score != null && <span style={{ marginLeft: "4px", color: "#64748b" }}>· Match score: {item.return_info.confidence_score}%</span>}
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
                <div style={{ display: "flex", flexDirection: "column", gap: "5px", background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: "6px", padding: "8px 10px" }}>
                  <strong style={{ color: "#1d4ed8", fontSize: "12px" }}>{confirmationMessage(order)}</strong>
                  <small style={{ color: "#64748b", fontSize: "11px" }}>Return and review options become available after delivery.</small>
                </div>
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
                {item.confidence_score != null && <span>· Match: <strong style={{ color: "#334155" }}>{item.confidence_score}%</strong></span>}
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
    );

  if (fullScreen) {
    return (
      <div className="account-page-container" style={{ maxWidth: "800px", margin: "40px auto", padding: "0 20px" }}>
        {drawerContent}
      </div>
    );
  }

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label={`Close ${title}`} />
      {drawerContent}
    </div>
  );
}

function ReturnImageEvidenceDrawer({ open, returnId, returns, orders, onClose, onRefreshData }) {
  const [front, setFront] = useState(null);
  const [back, setBack] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const record = returns.find((item) => item.id === returnId);
  const order = record ? orders.find((item) => item.id === record.order_id) : null;
  const returnedItem = order?.items?.find((item) => item.product_id === record?.product_id);
  if (!open || !record) return null;

  async function upload(file, side) {
    const slot = await post("/uploads/presign", { filename: file.name, content_type: file.type, kind: "return" });
    const response = await fetch(slot.upload_url, { method: "PUT", headers: { "Content-Type": file.type }, body: file });
    if (!response.ok) throw new Error(`${side} image upload failed (${response.status})`);
    return slot.object_key;
  }

  async function submitEvidence() {
    if (!front || !back || busy) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const [frontKey, backKey] = await Promise.all([upload(front, "Front"), upload(back, "Back")]);
      const response = await post(`/returns/${record.id}/image-attempt`, {
        front_image_key: frontKey,
        back_image_key: backKey,
        idempotency_key: crypto.randomUUID(),
      });
      setResult(response);
      setFront(null); setBack(null);
      await onRefreshData();
    } catch (reason) { setError(reason.message || "Return evidence could not be checked."); } finally { setBusy(false); }
  }

  const attemptsUsed = record.attempt_history?.length || 0;
  const canSubmit = ["pending_evidence", "needs_evidence"].includes(record.status) && attemptsUsed < 3;
  return <div className="drawer-layer open" style={{ zIndex: 100 }}><button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close return evidence" /><aside className="side-drawer" role="dialog" aria-modal="true" style={{ width: "min(600px, 100vw)", padding: 24, overflowY: "auto" }}>
    <div className="side-heading"><div><p>RETURN IMAGE CHECK</p><h2>Request {record.id}</h2></div><button type="button" onClick={onClose}><X /></button></div>
    {returnedItem && <div className="account-record"><strong>{returnedItem.product_name}</strong><small>Size {returnedItem.size || "Standard"} · Order {record.order_id}</small></div>}
    <div className="account-record"><strong>Status: {record.status.replaceAll("_", " ")}</strong><p>Attempt {attemptsUsed + (canSubmit ? 1 : 0)} of 3. Upload clear, well-lit photos of the exact front and back.</p>{record.similarity_aggregate != null && <p>Latest match: <strong>{record.similarity_aggregate.toFixed(2)}%</strong></p>}</div>
    {canSubmit && <section className="return-image-inputs"><label><Camera /> Product front<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(event) => setFront(event.target.files?.[0] || null)} /></label><label><Camera /> Product back<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(event) => setBack(event.target.files?.[0] || null)} /></label><button className="primary-cta wide" type="button" onClick={submitEvidence} disabled={!front || !back || busy}>{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />} Compare front and back</button></section>}
    {result && <div className={`agent-answer ${result.passed ? "success" : ""}`}><strong>{result.similarity_aggregate}% aggregate match</strong><span>{result.message}</span></div>}
    {error && <p className="field-error">{error}</p>}
    {record.status === "evidence_mismatch" && <div className="account-record"><strong>Evidence did not match after three attempts.</strong><p>Contact customer care if you need help with this decision.</p><Link className="primary-cta" href="/support">Contact customer care</Link></div>}
  </aside></div>;
}

function ReturnVerificationDrawer(props) {
  return <ReturnImageEvidenceDrawer {...props} />;
  /* Legacy video implementation retained below temporarily for source compatibility;
     the connected buyer flow above is the only rendered path. */
  const { open, returnId, returns, orders, onClose, onRefreshData } = props;
  const [videoFile, setVideoFile] = useState(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(10);
  const [mediaStream, setMediaStream] = useState(null);
  const [mediaRecorder, setMediaRecorder] = useState(null);
  const [actionDialog, setActionDialog] = useState(null);
  
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
      setActionDialog({ title: "Camera Access Error", text: "Could not access camera: " + err.message, type: "error" });
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
      setActionDialog({ title: "Invalid File Type", text: "Please select a valid video file.", type: "warning" });
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setActionDialog({ title: "File Too Large", text: "File is too large. Please select a video under 50MB.", type: "warning" });
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

      setStatusText("Evaluating return evidence...");
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
      setActionDialog({ title: "Verification Failed", text: "Failed to verify return: " + err.message, type: "error" });
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
              <span>Verification Match Score: <strong style={{ color: record.confidence_score >= 75 ? "#16a34a" : record.confidence_score >= 40 ? "#d97706" : "#ef4444" }}>{record.confidence_score}%</strong></span>
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
                  {uploading ? statusText : "Submit Evidence for Verification"}
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
        {actionDialog && (
          <ActionDialog
            isOpen={true}
            onClose={() => setActionDialog(null)}
            {...actionDialog}
          />
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
    selectedAddress.phone_lookup_validated &&
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
                          {addr.phone_lookup_validated ? (
                            <span style={{ color: "#16a34a" }}>✓ Phone Validated</span>
                          ) : (
                            <span style={{ color: "#ef4444" }}>✗ Phone Validation Required</span>
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
              <div className="consent-box" style={{ margin: 0 }}><Truck size={19} /><div><strong>WhatsApp delivery confirmation</strong><p>After placing the order, confirm ownership and your delivery date through WhatsApp.</p></div></div>
            )}

            {selectedAddress && (
              <div>
                {!isValidAddress ? (
                  <div style={{ background: "#fef3c7", border: "1px solid #fde68a", padding: "12px", borderRadius: "8px", color: "#d97706", fontSize: "13px" }}>
                    <strong>Validation failed:</strong> This address cannot be used for checkout. Confirm that the phone number passes carrier validation and that the coordinates match the address details.
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
              <Check size={15} /> Address verified
              <br />
              <Check size={15} /> Delivery consent recorded
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

function AddressManagerDrawer({ open, onClose, buyerId, fullScreen = false }) {
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const mapRef = useRef(null);
  const leafletMap = useRef(null);
  const marker = useRef(null);

  const successTimeoutRef = useRef(null);
  const errorTimeoutRef = useRef(null);

  function triggerSuccess(msg) {
    if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
    setSuccess(msg);
    successTimeoutRef.current = setTimeout(() => {
      setSuccess("");
    }, 1000);
  }

  function triggerError(msg) {
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    setError(msg);
    errorTimeoutRef.current = setTimeout(() => {
      setError("");
    }, 1000);
  }

  useEffect(() => {
    return () => {
      if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
      if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (!open) {
      if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
      if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
      const clearNotice = window.setTimeout(() => {
        setSuccess("");
        setError("");
        setFieldErrors({});
      }, 0);
      return () => window.clearTimeout(clearNotice);
    }
    return undefined;
  }, [open]);

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
    setFieldErrors({});
    try {
      let currentCoords = coords;
      if (marker.current) {
        const pos = marker.current.getLatLng();
        currentCoords = { latitude: pos.lat, longitude: pos.lng };
        setCoords(currentCoords);
      }
      const validation = await post("/addresses/reverse-geocode", currentCoords);
      const city = validation.city || "";
      const district = validation.district || validation.city || "";
      const state = validation.state || "";
      const postal_pin = validation.postal_pin || "";
      const label = validation.label || "";
      const locality = validation.locality || "";

      setFormData((prev) => ({
        ...prev,
        city,
        district,
        state,
        postal_pin,
        locality,
        address_line1: label
      }));
      triggerSuccess("Location geocoded successfully! Fields updated.");
    } catch (err) {
      triggerError("Geocoding failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleManualGeocode() {
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      const result = await post("/addresses/geocode", formData);
      const next = { latitude: result.latitude, longitude: result.longitude };
      setCoords(next);
      if (leafletMap.current && marker.current) {
        marker.current.setLatLng([next.latitude, next.longitude]);
        leafletMap.current.setView([next.latitude, next.longitude], 16);
      }
      triggerSuccess("Address located. Review the map pin, then verify your phone and save.");
    } catch (err) {
      triggerError("Address lookup failed: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      triggerError("This browser does not support location access.");
      return;
    }
    setBusy(true);
    setError("");
    setFieldErrors({});
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
            address_line1: result.label || "",
            locality: result.locality || "",
            city: result.city || "",
            district: result.district || result.city || "",
            state: result.state || "",
            postal_pin: result.postal_pin || "",
          }));
          triggerSuccess("Current location captured. Adjust the pin if needed.");
        } catch (err) {
          triggerError("Location captured, but address lookup failed: " + err.message);
        } finally {
          setBusy(false);
        }
      },
      (reason) => {
        setBusy(false);
        triggerError(reason.message || "Location permission was not granted.");
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      let currentCoords = coords;
      if (marker.current) {
        const pos = marker.current.getLatLng();
        currentCoords = { latitude: pos.lat, longitude: pos.lng };
        setCoords(currentCoords);
      }
      const payload = {
        ...formData,
        latitude: currentCoords.latitude,
        longitude: currentCoords.longitude,
      };
      if (mode === "add") {
        await post("/addresses", payload);
      } else {
        await request(`/addresses/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(payload)
        });
      }
      triggerSuccess("Address saved. The phone number was validated by carrier lookup.");
      setMode("list");
      loadAddresses();
    } catch (err) {
      if (err.detail && err.detail.errors) {
        setFieldErrors(err.detail.errors);
        triggerError(err.detail.message || "Validation failed");
      } else {
        triggerError(err.message || "Failed to save address");
      }
    } finally {
      setBusy(false);
    }
  }

  function handleDelete(id) {
    setConfirmDeleteId(id);
    setDeleteError("");
  }

  async function handleDeleteConfirm() {
    if (!confirmDeleteId) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await del(`/addresses/${confirmDeleteId}`);
      setConfirmDeleteId(null);
      loadAddresses();
      triggerSuccess("Address deleted successfully.");
    } catch (err) {
      setDeleteError("Failed to delete address: " + err.message);
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleSetDefault(id) {
    try {
      await post(`/addresses/${id}/default`);
      loadAddresses();
      triggerSuccess("Default address updated.");
    } catch (err) {
      triggerError("Failed to set default: " + err.message);
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
    setMode("add");
    setError("");
    setSuccess("");
    setFieldErrors({});
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
    setEditingId(addr.id);
    setMode("edit");
    setError("");
    setSuccess("");
    setFieldErrors({});
  }

  const drawerContent = (
    <aside className={fullScreen ? "full-screen-account-page" : "side-drawer"} role="dialog" aria-modal="true" aria-label="Manage Addresses" style={fullScreen ? { width: "100%", background: "white", padding: "24px", borderRadius: "12px", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.05)", position: "relative" } : { width: "min(550px, 100vw)" }}>
      {fullScreen && (
        <button type="button" onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: "6px", color: "var(--muted)", fontWeight: "600", fontSize: "14px", padding: 0, marginBottom: "20px" }}>
          <ArrowLeft size={16} /> Back to Shop
        </button>
      )}
      <div className="side-heading" style={fullScreen ? { borderBottom: "1px solid var(--line)", paddingBottom: "16px", marginBottom: "20px" } : {}}>
        <div><p>YOUR PROFILE</p><h2>{mode === "list" ? "Manage Addresses" : mode === "add" ? "Add Address" : "Edit Address"}</h2></div>
        {!fullScreen && <button type="button" onClick={onClose} aria-label="Close"><X size={20} /></button>}
      </div>

      {error && (
        <div style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          zIndex: 9999,
          background: "rgba(229, 72, 77, 0.95)",
          backdropFilter: "blur(4px)",
          color: "#fff",
          padding: "16px 24px",
          borderRadius: "12px",
          fontWeight: "600",
          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.3)",
          textAlign: "center",
          pointerEvents: "none",
          maxWidth: "90vw"
        }} role="alert">
          {error}
        </div>
      )}
      {success && (
        <div style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          zIndex: 9999,
          background: "rgba(22, 163, 74, 0.95)",
          backdropFilter: "blur(4px)",
          color: "#fff",
          padding: "16px 24px",
          borderRadius: "12px",
          fontWeight: "600",
          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.3)",
          textAlign: "center",
          pointerEvents: "none",
          maxWidth: "90vw"
        }} role="status">
          {success}
        </div>
      )}

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
                    Phone: {addr.phone} {addr.phone_lookup_validated ? "· Validated by carrier lookup" : "· Lookup required"}
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
                {fieldErrors.recipient_name && <small className="field-error">{fieldErrors.recipient_name}</small>}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-phone" style={{ fontWeight: 600 }}>Phone Number *</label>
                <div style={{ display: "flex", gap: "8px" }}>
                  <select value={formData.country} onChange={(e) => setFormData({ ...formData, country: e.target.value })} aria-label="Phone country"><option>India</option><option>United States</option><option>United Kingdom</option></select>
                  <input id="address-phone" value={formData.phone} onChange={(e) => setFormData({ ...formData, phone: e.target.value })} placeholder="9876543210 or +919876543210" inputMode="tel" autoComplete="tel" required style={{ flex: 1 }} />
                </div>
                <small>For India, enter either the 10-digit mobile number or +91 followed by the number.</small>
                {fieldErrors.phone && <small className="field-error">{fieldErrors.phone}</small>}
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
                {fieldErrors.address_line1 && <small className="field-error">{fieldErrors.address_line1}</small>}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-line-2" style={{ fontWeight: 600 }}>Address Line 2 (Optional)</label>
                <input id="address-line-2" value={formData.address_line2} onChange={(e) => setFormData({ ...formData, address_line2: e.target.value })} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label htmlFor="address-locality" style={{ fontWeight: 600 }}>Locality (Optional)</label>
                <input id="address-locality" value={formData.locality} onChange={(e) => setFormData({ ...formData, locality: e.target.value })} />
                {fieldErrors.locality && <small className="field-error">{fieldErrors.locality}</small>}
              </div>
              <div style={{ display: "flex", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-city" style={{ fontWeight: 600 }}>City *</label>
                  <input id="address-city" value={formData.city} onChange={(e) => setFormData({ ...formData, city: e.target.value })} required />
                  {fieldErrors.city && <small className="field-error">{fieldErrors.city}</small>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-district" style={{ fontWeight: 600 }}>District *</label>
                  <input id="address-district" value={formData.district} onChange={(e) => setFormData({ ...formData, district: e.target.value })} required />
                  {fieldErrors.district && <small className="field-error">{fieldErrors.district}</small>}
                </div>
              </div>
              <button type="button" className="secondary-cta wide" onClick={handleManualGeocode} disabled={busy}>Locate this manually entered address on the map</button>
              <div style={{ display: "flex", gap: "12px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-state" style={{ fontWeight: 600 }}>State *</label>
                  <input id="address-state" value={formData.state} onChange={(e) => setFormData({ ...formData, state: e.target.value })} required />
                  {fieldErrors.state && <small className="field-error">{fieldErrors.state}</small>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                  <label htmlFor="address-pin" style={{ fontWeight: 600 }}>Postal PIN *</label>
                  <input id="address-pin" value={formData.postal_pin} onChange={(e) => setFormData({ ...formData, postal_pin: e.target.value })} maxLength={6} required />
                  {fieldErrors.postal_pin && <small className="field-error">{fieldErrors.postal_pin}</small>}
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

        {confirmDeleteId && (
          <ConfirmDeleteDialog
            isOpen={true}
            onClose={() => setConfirmDeleteId(null)}
            onConfirm={handleDeleteConfirm}
            deleting={deleteBusy}
            error={deleteError}
          />
        )}
    </aside>
  );

  if (fullScreen) {
    return (
      <div className="account-page-container" style={{ maxWidth: "800px", margin: "40px auto", padding: "0 20px" }}>
        {drawerContent}
      </div>
    );
  }

  return (
    <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
      <button className="drawer-scrim" type="button" onClick={onClose} aria-label="Close address manager" />
      {drawerContent}
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
                  <option value="delivery_boy">Delivery person</option>
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
  const pathname = usePathname();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);

  // Dialog/Modal states
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const [returnRequestData, setReturnRequestData] = useState(null); // { orderId, productId, returnType }
  const [returnRequestBusy, setReturnRequestBusy] = useState(false);
  const [returnRequestError, setReturnRequestError] = useState("");

  const [reviewComposerData, setReviewComposerData] = useState(null); // { productId, orderId }
  const [reviewComposerBusy, setReviewComposerBusy] = useState(false);
  const [reviewComposerError, setReviewComposerError] = useState("");

  const [actionDialogConfig, setActionDialogConfig] = useState(null); // { title, text, type }

  const [cardPaymentData, setCardPaymentData] = useState(null); // { addressId, amount, orderId }
  const [cardPaymentBusy, setCardPaymentBusy] = useState(false);
  const [cardPaymentError, setCardPaymentError] = useState("");
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
  const [vishwasOpen, setVishwasOpen] = useState(false);
  const [vishwasInitialMsg, setVishwasInitialMsg] = useState("");
  const [vishwasInitialProduct, setVishwasInitialProduct] = useState(null);
  const [vishwasInitialPrompts, setVishwasInitialPrompts] = useState([]);
  const isOverlayOpen = !!(
    drawer ||
    vishwasOpen ||
    authModalOpen ||
    reviewSummary ||
    returnRequestData ||
    reviewComposerData ||
    actionDialogConfig
  );

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

  useEffect(() => {
    const viewingOrders = drawer === "orders" || pathname?.startsWith("/account/orders");
    if (!viewingOrders || auth?.user?.role !== "buyer") return undefined;
    const interval = window.setInterval(() => {
      listMyOrders().then(setOrders).catch(() => {});
    }, 5000);
    return () => window.clearInterval(interval);
  }, [auth?.user?.role, drawer, pathname]);

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

  function openVishwasSamvad(product = null, options = {}) {
    requireAuth(() => {
      const contextProduct = product || selected || null;
      setVishwasInitialProduct(contextProduct);
      setVishwasInitialMsg(options.message || "");
      setVishwasInitialPrompts(options.prompts || (contextProduct ? [
        "Is kapde ka material kaisa hai?",
        "Is kapde ki return policy kya hai?",
        "Is kapde ka rang kya hai?",
      ] : []));
      setVishwasOpen(true);
    });
  }

  function handleAuthenticated(session) {
    const pendingAction = pendingAfterAuth;
    setAuth(session);
    setAuthModalOpen(false);
    setToast(`Welcome, ${session.user.name}`);
    setPendingAfterAuth(null);
    if (session.user.role === "delivery_boy") {
      router.push("/delivery");
      return;
    }
    if (session.user.role === "seller") {
      router.push("/seller");
      return;
    }
    if (session.user.role === "admin") {
      router.push("/admin");
      return;
    }
    router.push("/");
    if (pendingAction) pendingAction(session.user.id);
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


  function startReturn(orderId, productId, returnType = "refund") {
    setReturnRequestData({ orderId, productId, returnType });
    setReturnRequestError("");
  }

  async function handleReturnRequestSubmit(reason) {
    if (!returnRequestData) return;
    setReturnRequestBusy(true);
    setReturnRequestError("");
    const { orderId, productId, returnType } = returnRequestData;
    try {
      const res = await createReturnRequest(orderId, productId, reason, returnType);
      setReturnRequestData(null);
      await refreshAccountData();
      setSelectedReturnId(res.id);
      setDrawer("return-verify");
      setToast(`${returnType === "exchange" ? "Exchange" : "Return"} request created. Add evidence for verification.`);
    } catch (reasonError) {
      setReturnRequestError(reasonError.message || "Could not create return");
    } finally {
      setReturnRequestBusy(false);
    }
  }

  function startReview(productId, orderId) {
    setReviewComposerData({ productId, orderId });
    setReviewComposerError("");
  }

  async function handleReviewComposerSubmit({ rating, text, file }) {
    if (!reviewComposerData) return;
    setReviewComposerBusy(true);
    setReviewComposerError("");
    const { productId, orderId } = reviewComposerData;
    try {
      let mediaKey = null;
      if (file) {
        const extension = file.type.split("/")[1] || "png";
        const presign = await post("/uploads/presign", {
          kind: "review",
          filename: `review_photo.${extension}`,
          content_type: file.type
        });
        const uploadRes = await fetch(presign.upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": file.type }
        });
        if (!uploadRes.ok) {
          throw new Error("Failed to upload review photo.");
        }
        mediaKey = presign.object_key;
      }
      await createReview({
        product_id: productId,
        order_id: orderId,
        rating,
        text,
        image_key: mediaKey
      });
      setReviewComposerData(null);
      await refreshAccountData();
      if (selected?.id === productId) {
        setSelected(await request(`/storefront/products/${productId}`));
      }
      setToast("Verified review posted successfully");
    } catch (reason) {
      setReviewComposerError(reason.message || "Could not post this review");
    } finally {
      setReviewComposerBusy(false);
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
      setToast(`Language set to ${label}`);
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

  async function execute(message, operation) {
    setBusy(true);
    try {
      return await operation();
    } catch (reason) {
      setToast(reason.message || "That check could not be completed");
      throw reason;
    } finally {
      setBusy(false);
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
      setSizeSaathi(null);
      const payload = await execute("Size Saathi is checking purchase and fit history...", () => post("/size/recommend", { buyer_id: buyerId, product_id: selected.id }));
      const sizeResult = payload.results.size_translator;
      const recommendation = sizeResult?.data?.recommended_size;
      const message = sizeResult?.user_message?.en || sizeResult?.summary || "";
      setSizeSaathi({ size: recommendation || null, source: sizeResult?.data?.source, message });
      if (recommendation) setToast(`Size Saathi recommends ${recommendation}`);
    });
  }

  async function checkReview() {
    if (!selected) return;
    try {
      const payload = await execute("Summarizing all reviews...", () =>
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
      const payload = await execute("Retrieving verified details...", () => post("/voice/query", { buyer_id: buyerId, product_id: selected.id, text: question, language }));
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
      const payload = await execute("Transcribing and processing your question...", () => post("/voice/query", { buyer_id: buyerId, product_id: selected.id, audio_key: presign.object_key, language }));
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
          ? "Order placed — please confirm it on WhatsApp"
          : "Order placed, but the WhatsApp confirmation could not be queued"
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
      const selectedAddress = addresses.find((a) => a.id === addressId);
      setCardPaymentData({
        addressId,
        amount: orderData.total_amount,
        orderId: orderData.order_id,
        selectedAddress
      });
      setCardPaymentError("");
    } catch (reason) {
      setToast(reason.message || "Could not initialize prepaid order");
    } finally {
      setBusy(false);
    }
  }

  async function handleCardPaymentSubmit({ cardNumber, expiryDate, cvv }) {
    if (!cardPaymentData) return;
    setCardPaymentBusy(true);
    setCardPaymentError("");
    const { orderId, selectedAddress } = cardPaymentData;
    try {
      const payment = await post(`/orders/${orderId}/verify-demo-payment`, {
        card_number: cardNumber.replace(/\s/g, ""),
        expiry_date: expiryDate,
        cvv
      });
      setLastOrderId(orderId);
      setLastOrderSummary({ amount: cardPaymentData.amount, paymentMode: "prepaid", address: selectedAddress });
      setToast(
        payment.delivery_confirmation_queued
          ? "Payment verified — please confirm the order on WhatsApp"
          : "Payment verified, but the WhatsApp confirmation could not be scheduled"
      );
      setCardPaymentData(null);
      await refreshCart();
      await refreshAccountData();
      setCheckoutStep("done");
    } catch (err) {
      setCardPaymentError(err.message || "Payment failed");
    } finally {
      setCardPaymentBusy(false);
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
          sizeSaathi={sizeSaathi ? { ...sizeSaathi, audioUrl: audioUrl(sizeSaathi.audioKey) } : null}
          onOpenVishwasSamvad={openVishwasSamvad}
        />
        {!isOverlayOpen && (
          <button type="button" className="vishwas-samvad-launcher-btn" onClick={() => openVishwasSamvad(selected)} aria-label="Open Vishwas Saathi"><MessageCircle size={18} /><span><strong>Vishwas Saathi</strong><small>Ask about this product or your shopping journey</small></span></button>
        )}
        {vishwasOpen && <div className="vishwas-samvad-panel"><VishwasSamvadChat auth={auth} onClose={() => setVishwasOpen(false)} initialMessage={vishwasInitialMsg} initialProduct={vishwasInitialProduct} initialPrompts={vishwasInitialPrompts} /></div>}
        <CartDrawer items={cart} open={drawer === "cart"} busyItem={cartBusy} onClose={() => setDrawer(null)} onUpdate={updateCartQuantity} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); })} />
        <CheckoutDrawer open={drawer === "checkout"} busy={busy} step={checkoutStep} orderId={lastOrderId} orderSummary={lastOrderSummary} onClose={() => setDrawer(null)} onGoOrders={() => setDrawer("orders")} onConfirm={confirmOrder} onConfirmPrepaid={confirmOrderPrepaid} addresses={addresses} onManageAddresses={() => setDrawer("addresses")} buyerName={auth?.user?.name} />
        <AddressManagerDrawer open={drawer === "addresses"} onClose={() => { setDrawer(null); refreshAccountData(); }} buyerId={auth?.user?.id} />
        <AccountDataDrawer type={drawer} open={["orders", "wishlist", "returns"].includes(drawer)} orders={orders} wishlist={wishlist} returns={returns} onClose={() => setDrawer(null)} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} />
        <ReturnVerificationDrawer open={drawer === "return-verify"} returnId={selectedReturnId} returns={returns} orders={orders} onClose={() => { setDrawer(null); refreshAccountData(); }} onRefreshData={refreshAccountData} />
        <AuthModal open={authModalOpen} onClose={() => { setAuthModalOpen(false); setPendingAfterAuth(null); }} onAuthenticated={handleAuthenticated} />
        <ReviewSummaryDialog data={reviewSummary} onClose={() => setReviewSummary(null)} />
        {toast && <div className="toast" role="status" aria-live="polite"><Check size={16} /> {toast}</div>}
      </>
    );
  }

  const isAccountPage = pathname && pathname.startsWith("/account/");

  return (
    <div className="storefront">
      <header className="site-header">
        <div className="header-main">
          <button className="mobile-menu" type="button" onClick={() => setMobileNavOpen((open) => !open)} aria-label={mobileNavOpen ? "Close menu" : "Open menu"} aria-expanded={mobileNavOpen}><Menu /></button>
          <a className="logo" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a>
          <label className="search-box"><Search size={19} /><input value={search} onChange={(event) => { setSearch(event.target.value); setVisibleCount(50); }} placeholder="Try Saree, Kurti or Search by Product Code" /><kbd>⌘ K</kbd></label>
          <nav className={`utility-nav ${mobileNavOpen ? "open" : ""}`} aria-label="Account navigation">
            <button type="button" onClick={() => openVishwasSamvad()}><MessageCircle size={19} /><span>Vishwas Saathi</span></button>
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
        {pathname === "/account/cart" ? (
          <CartDrawer items={cart} open={true} busyItem={cartBusy} onClose={() => router.push("/")} onUpdate={updateCartQuantity} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); })} fullScreen={true} />
        ) : pathname === "/account/orders" ? (
          <AccountDataDrawer type="orders" open={true} orders={orders} wishlist={wishlist} returns={returns} onClose={() => router.push("/")} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} fullScreen={true} />
        ) : pathname === "/account/returns" ? (
          <AccountDataDrawer type="returns" open={true} orders={orders} wishlist={wishlist} returns={returns} onClose={() => router.push("/")} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} fullScreen={true} />
        ) : pathname === "/account/wishlist" ? (
          <AccountDataDrawer type="wishlist" open={true} orders={orders} wishlist={wishlist} returns={returns} onClose={() => router.push("/")} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} fullScreen={true} />
        ) : pathname === "/account/addresses" ? (
          <AddressManagerDrawer open={true} onClose={() => router.push("/")} buyerId={auth?.user?.id} fullScreen={true} />
        ) : (
          <>
            <section className="hero">
              <div className="hero-copy"><p><ShieldCheck size={14} /> AGENT-PROTECTED SHOPPING</p><h1>Smart shopping.<br /><em>Safer at every step.</em></h1><span>Discover value-first products while eight Kavach Saathi agents verify listings, sizes, reviews, delivery and returns.</span><div><button className="hero-primary" type="button" onClick={() => document.querySelector("#products")?.scrollIntoView({ behavior: "smooth" })}>Shop protected deals <ArrowRight size={18} /></button></div><small><Check size={13} /> Persistent evidence <Check size={13} /> Grounded AI <Check size={13} /> Fair return policy</small></div>
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
              <div className="story-steps">{Object.entries(AGENTS).map(([key, agent]) => { const Icon = agent.icon; return <div className="story-step" key={key}><span>{agent.number}</span><Icon size={19} /><strong>{agent.short}</strong></div>; })}</div>
            </section>
          </>
        )}
      </main>

      <footer className="site-footer"><a className="logo inverse" href="#top"><span>K</span><div><strong>Kavach</strong><small>SAATHI SHOP</small></div></a><p>Agent-protected commerce with persistent evidence and auditable decisions.</p><div><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">API docs</a></div></footer>

      {!isAccountPage && <CartDrawer items={cart} open={drawer === "cart"} busyItem={cartBusy} onClose={() => setDrawer(null)} onUpdate={updateCartQuantity} onRemove={removeFromCart} onCheckout={() => requireAuth(() => { setDrawer("checkout"); setCheckoutStep("address"); })} />}
      <CheckoutDrawer open={drawer === "checkout"} busy={busy} step={checkoutStep} orderId={lastOrderId} orderSummary={lastOrderSummary} onClose={() => setDrawer(null)} onGoOrders={() => router.push("/account/orders")} onConfirm={confirmOrder} onConfirmPrepaid={confirmOrderPrepaid} addresses={addresses} onManageAddresses={() => router.push("/account/addresses")} buyerName={auth?.user?.name} />
      {!isAccountPage && <AddressManagerDrawer open={drawer === "addresses"} onClose={() => { setDrawer(null); refreshAccountData(); }} buyerId={auth?.user?.id} />}
      {!isAccountPage && <AccountDataDrawer type={drawer} open={["orders", "wishlist", "returns"].includes(drawer)} orders={orders} wishlist={wishlist} returns={returns} onClose={() => setDrawer(null)} onOpenProduct={(productId) => router.push(`/products/${productId}`)} onRemoveWishlist={(productId) => toggleWishlist({ id: productId })} onStartReturn={startReturn} onStartReview={startReview} onViewReturn={handleViewReturn} onSubmitFitFeedback={submitFitFeedback} />}
      <ReturnVerificationDrawer open={drawer === "return-verify"} returnId={selectedReturnId} returns={returns} orders={orders} onClose={() => { setDrawer(null); refreshAccountData(); }} onRefreshData={refreshAccountData} />
      <AuthModal open={authModalOpen} onClose={() => { setAuthModalOpen(false); setPendingAfterAuth(null); }} onAuthenticated={handleAuthenticated} />
      <ReviewSummaryDialog data={reviewSummary} onClose={() => setReviewSummary(null)} />

      {returnRequestData && (
        <ReturnRequestDialog
          isOpen={true}
          onClose={() => setReturnRequestData(null)}
          onConfirm={handleReturnRequestSubmit}
          busy={returnRequestBusy}
          error={returnRequestError}
          returnType={returnRequestData.returnType}
        />
      )}
      {reviewComposerData && (
        <ReviewComposerDialog
          isOpen={true}
          onClose={() => setReviewComposerData(null)}
          onSubmit={handleReviewComposerSubmit}
          busy={reviewComposerBusy}
          error={reviewComposerError}
          orderId={reviewComposerData.orderId}
          product={orders.find((order) => order.id === reviewComposerData.orderId)?.items.find((item) => item.product_id === reviewComposerData.productId)}
        />
      )}
      {actionDialogConfig && (
        <ActionDialog
          isOpen={true}
          onClose={() => setActionDialogConfig(null)}
          {...actionDialogConfig}
        />
      )}
      {cardPaymentData && (
        <CardPaymentDialog
          key={cardPaymentData.orderId}
          isOpen={true}
          onClose={() => setCardPaymentData(null)}
          onSubmit={handleCardPaymentSubmit}
          amount={cardPaymentData.amount}
          busy={cardPaymentBusy}
          error={cardPaymentError}
        />
      )}
      {/* Vishwas Saathi Persistent Widget */}
      {!isOverlayOpen && (
        <button type="button" className="vishwas-samvad-launcher-btn" onClick={() => vishwasOpen ? setVishwasOpen(false) : openVishwasSamvad()} aria-label="Open Vishwas Saathi">
          <MessageCircle size={18} /><span><strong>Vishwas Saathi</strong><small>Ask about this page or your shopping journey</small></span>
        </button>
      )}

      {vishwasOpen && (
        <div className="vishwas-samvad-panel">
          <VishwasSamvadChat
            auth={auth}
            onClose={() => setVishwasOpen(false)}
            initialMessage={vishwasInitialMsg}
            initialProduct={vishwasInitialProduct}
            initialPrompts={vishwasInitialPrompts}
          />
        </div>
      )}

      {toast && <div className="toast" role="status" aria-live="polite"><Check size={16} /> {toast}</div>}
    </div>
  );
}

function Modal({ isOpen, onClose, title, children }) {
  const modalRef = useRef(null);
  const previouslyFocusedRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = Array.from(modalRef.current.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    if (isOpen) {
      previouslyFocusedRef.current = document.activeElement;
      document.addEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "hidden";

      // Focus trapping
      const focusable = modalRef.current?.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable && focusable.length > 0) {
        focusable[0].focus();
      }
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
      previouslyFocusedRef.current?.focus?.();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div style={{ position: "fixed", top: 0, left: 0, width: "100%", height: "100%", background: "rgba(0,0,0,0.5)", zIndex: 3000, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
      <button style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", background: "none", border: "none" }} onClick={onClose} aria-label="Close modal" />
      <div ref={modalRef} role="dialog" aria-modal="true" style={{ background: "white", padding: "24px", borderRadius: "12px", width: "100%", maxWidth: "450px", display: "flex", flexDirection: "column", gap: "16px", boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)", position: "relative", zIndex: 3001 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line)", paddingBottom: "12px" }}>
          <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "600" }}>{title}</h3>
          <button type="button" onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }} aria-label="Close modal button"><X size={20} /></button>
        </div>
        <div style={{ overflowY: "auto", maxHeight: "70vh" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

function ConfirmDeleteDialog({ isOpen, onClose, onConfirm, deleting, error }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Confirm Address Deletion">
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <p style={{ margin: 0, fontSize: "14px", color: "#475569" }}>
          Are you sure you want to delete this address? This action cannot be undone.
        </p>
        {error && <div style={{ color: "#ef4444", fontSize: "13px", fontWeight: "600" }}>{error}</div>}
        <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end" }}>
          <button type="button" className="secondary-cta" onClick={onClose} disabled={deleting}>Cancel</button>
          <button type="button" className="primary-cta" onClick={onConfirm} disabled={deleting}>
            {deleting ? <LoaderCircle className="spin" size={14} /> : null}
            Delete
          </button>
        </div>
      </div>
    </Modal>
  );
}

function ReturnRequestDialog({ isOpen, onClose, onConfirm, busy, error, returnType }) {
  const [reason, setReason] = useState("");

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${returnType === "exchange" ? "Exchange" : "Return"} Request`}>
      <form onSubmit={(e) => { e.preventDefault(); onConfirm(reason); }} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div>
          <label htmlFor="return-reason" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>
            Why are you {returnType === "exchange" ? "exchanging" : "returning"} this product?
          </label>
          <textarea
            id="return-reason"
            required
            rows={4}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Please describe the issue in detail..."
            style={{ width: "100%", padding: "10px", border: "1px solid var(--border)", borderRadius: "6px", resize: "none" }}
          />
        </div>
        {error && <div style={{ color: "#ef4444", fontSize: "13px", fontWeight: "600" }}>{error}</div>}
        <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
          <button type="button" className="secondary-cta" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="primary-cta" disabled={busy || !reason.trim()}>
            {busy ? <LoaderCircle className="spin" size={14} /> : null}
            Submit Request
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ReviewComposerDialog({ isOpen, onClose, onSubmit, busy, error, product, orderId }) {
  const [rating, setRating] = useState(5);
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : ""), [file]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    if (!selected.type.startsWith("image/")) {
      setFileError("Please select a valid image file.");
      setFile(null);
      return;
    }
    if (selected.size > 5 * 1024 * 1024) {
      setFileError("Image size must be under 5MB.");
      setFile(null);
      return;
    }
    setFileError("");
    setFile(selected);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (trimmed.length < 10) {
      setFileError("Review text must be at least 10 characters long.");
      return;
    }
    if (!file) {
      setFileError("Please attach exactly one product photo.");
      return;
    }
    setFileError("");
    onSubmit({ rating, text: trimmed, file });
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Review this product">
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          {product?.image_url && <img src={assetUrl(product.image_url)} alt="" style={{ width: 56, height: 56, borderRadius: 8, objectFit: "cover" }} />}
          <div><strong style={{ display: "block", fontSize: 14 }}>{product?.product_name || "Purchased product"}</strong><small style={{ color: "#64748b" }}>Order {orderId}</small></div>
        </div>
        <div>
          <span style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>Rating *</span>
          <div role="radiogroup" aria-label="Rating" style={{ display: "flex", gap: 4 }}>
            {[1, 2, 3, 4, 5].map((value) => <button key={value} type="button" role="radio" aria-checked={rating === value} aria-label={`${value} star${value === 1 ? "" : "s"}`} onClick={() => setRating(value)} style={{ border: 0, background: "none", padding: 3, cursor: "pointer", color: value <= rating ? "#f59e0b" : "#cbd5e1" }}><Star size={26} fill="currentColor" /></button>)}
          </div>
        </div>
        <div>
          <label htmlFor="review-text" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>Review Details *</label>
          <textarea
            id="review-text"
            rows={4}
            value={text}
            maxLength={2000}
            onChange={(e) => setText(e.target.value)}
            placeholder="Write your review here (minimum 10 characters)..."
            style={{ width: "100%", padding: "10px", border: "1px solid var(--border)", borderRadius: "6px", resize: "none" }}
          />
          <small style={{ display: "block", textAlign: "right", color: "#64748b" }}>{text.length}/2000</small>
        </div>

        <div>
          <label htmlFor="review-photo" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>Attach Photo *</label>
          <input
            id="review-photo"
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            style={{ display: "block", width: "100%" }}
          />
          {fileError && <div style={{ color: "#ef4444", fontSize: "12px", marginTop: "4px" }}>{fileError}</div>}
          <small style={{ color: "#64748b" }}>JPG, PNG, or WebP; maximum 5 MB.</small>
          {previewUrl && <div style={{ marginTop: 8, display: "flex", gap: 10, alignItems: "center" }}><img src={previewUrl} alt="Review upload preview" style={{ width: 72, height: 72, objectFit: "cover", borderRadius: 8 }} /><button type="button" className="secondary-cta compact" onClick={() => setFile(null)}>Remove photo</button></div>}
        </div>

        {error && <div style={{ color: "#ef4444", fontSize: "13px", fontWeight: "600" }}>{error}</div>}
        <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
          <button type="button" className="secondary-cta" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="primary-cta" disabled={busy || fileError || !text.trim() || !file}>
            {busy ? <LoaderCircle className="spin" size={14} /> : null}
            Submit Review
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ActionDialog({ isOpen, onClose, title, text, type = "info" }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title}>
      <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
        {type === "error" ? (
          <ShieldAlert size={24} color="#ef4444" style={{ flexShrink: 0 }} />
        ) : type === "warning" ? (
          <AlertTriangle size={24} color="#d97706" style={{ flexShrink: 0 }} />
        ) : (
          <ShieldCheck size={24} color="var(--plum)" style={{ flexShrink: 0 }} />
        )}
        <p style={{ margin: 0, fontSize: "14px", color: "#475569", lineHeight: "1.5" }}>
          {text}
        </p>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
        <button type="button" className="primary-cta" onClick={onClose}>
          OK
        </button>
      </div>
    </Modal>
  );
}

function CardPaymentDialog({ isOpen, onClose, onSubmit, amount, busy, error }) {
  const [cardNumber, setCardNumber] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [cvv, setCvv] = useState("");



  const handleCardNumberChange = (e) => {
    const value = e.target.value.replace(/\D/g, "").slice(0, 16);
    const matches = value.match(/\d{4,16}/g);
    const match = (matches && matches[0]) || "";
    const parts = [];

    for (let i = 0, len = match.length; i < len; i += 4) {
      parts.push(match.substring(i, i + 4));
    }

    if (parts.length > 0) {
      setCardNumber(parts.join(" "));
    } else {
      setCardNumber(value);
    }
  };

  const handleExpiryChange = (e) => {
    const value = e.target.value.replace(/\D/g, "").slice(0, 4);
    if (value.length >= 2) {
      setExpiryDate(`${value.slice(0, 2)}/${value.slice(2, 4)}`);
    } else {
      setExpiryDate(value);
    }
  };

  const handleCvvChange = (e) => {
    const value = e.target.value.replace(/\D/g, "").slice(0, 3);
    setCvv(value);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({ cardNumber, expiryDate, cvv });
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Secure Card Payment">
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <p style={{ margin: 0, fontSize: "13px", color: "#64748b" }}>
          Please enter your test credit or debit card details to complete the payment.
        </p>

        <div>
          <label htmlFor="card-number" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>Card Number</label>
          <input
            id="card-number"
            required
            placeholder="4111 1111 1111 1111"
            value={cardNumber}
            onChange={handleCardNumberChange}
            style={{ width: "100%", padding: "10px", border: "1px solid var(--border)", borderRadius: "6px" }}
          />
        </div>

        <div style={{ display: "flex", gap: "12px" }}>
          <div style={{ flex: 1 }}>
            <label htmlFor="expiry" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>Expiry Date</label>
            <input
              id="expiry"
              required
              placeholder="MM/YY"
              value={expiryDate}
              onChange={handleExpiryChange}
              style={{ width: "100%", padding: "10px", border: "1px solid var(--border)", borderRadius: "6px" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label htmlFor="cvv" style={{ display: "block", marginBottom: "6px", fontWeight: "600", fontSize: "13px" }}>CVV</label>
            <input
              id="cvv"
              required
              placeholder="123"
              type="password"
              value={cvv}
              onChange={handleCvvChange}
              style={{ width: "100%", padding: "10px", border: "1px solid var(--border)", borderRadius: "6px" }}
            />
          </div>
        </div>

        {error && <div style={{ color: "#ef4444", fontSize: "13px", fontWeight: "600" }}>{error}</div>}
        <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", borderTop: "1px solid var(--line)", paddingTop: "12px" }}>
          <button type="button" className="secondary-cta" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="primary-cta" disabled={busy || cardNumber.replace(/\s/g, "").length !== 16 || expiryDate.length !== 5 || cvv.length !== 3}>
            {busy ? <LoaderCircle className="spin" size={14} /> : null}
            Pay {money(amount)}
          </button>
        </div>
      </form>
    </Modal>
  );
}
