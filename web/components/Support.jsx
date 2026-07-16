"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Headphones, Mail, Phone, ArrowLeft, ShieldCheck, LoaderCircle, Check, CircleUserRound } from "lucide-react";
import { loadAuthSession, request, post } from "@/lib/api";

export default function Support() {
  const router = useRouter();
  const [auth] = useState(() => loadAuthSession());
  const [supportInfo, setSupportInfo] = useState({ phone: "", email: "" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loggingStatus, setLoggingStatus] = useState(""); // "logging", "logged", ""

  useEffect(() => {
    // Fetch support info from backend (Task 14)
    request("/support/info")
      .then((data) => {
        setSupportInfo(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load support contact information.");
        setLoading(false);
      });
  }, []);

  async function handleInteraction(channel) {
    if (!auth?.user) {
      // If not logged in, just proceed with normal link open
      return;
    }
    setLoggingStatus("logging");
    try {
      // Create interaction record on the backend (Task 14)
      await post("/support/log", { channel });
      setLoggingStatus("logged");
      setTimeout(() => setLoggingStatus(""), 1200);
    } catch (err) {
      console.error("Failed to log support interaction:", err);
      setLoggingStatus("");
    }
  }

  return (
    <div className="storefront" style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--soft, #f8f5f3)" }}>
      {/* Site Header */}
      <header className="site-header">
        <div className="header-main" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", minHeight: "64px", padding: "10px max(20px, calc((100vw - 1280px) / 2))" }}>
          <Link className="logo" href="/">
            <span>K</span>
            <div>
              <strong>Kavach</strong>
              <small>SAATHI SHOP</small>
            </div>
          </Link>
          <button 
            type="button" 
            onClick={() => router.push("/")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              background: "white",
              border: "1px solid var(--line, #e7e0e3)",
              borderRadius: "10px",
              padding: "8px 16px",
              fontSize: "12px",
              fontWeight: "600",
              cursor: "pointer",
            }}
          >
            <ArrowLeft size={16} /> Back to shop
          </button>
        </div>
      </header>

      {/* Main Support Panel */}
      <main style={{ flex: 1, display: "flex", justifyContent: "center", alignItems: "center", padding: "40px 20px" }}>
        <div 
          style={{
            background: "white",
            border: "1px solid var(--line, #e7e0e3)",
            borderRadius: "20px",
            boxShadow: "var(--shadow, 0 24px 70px rgb(76 28 52 / 12%))",
            width: "100%",
            maxWidth: "520px",
            padding: "40px 30px",
            textAlign: "center",
            display: "flex",
            flexDirection: "column",
            gap: "24px"
          }}
        >
          {/* Header Icon */}
          <div 
            style={{ 
              alignSelf: "center", 
              width: "72px", 
              height: "72px", 
              borderRadius: "50%", 
              background: "var(--pink, #f7e8f0)", 
              color: "var(--plum, #7b1748)", 
              display: "grid", 
              placeItems: "center" 
            }}
          >
            <Headphones size={36} />
          </div>

          {/* Heading */}
          <div>
            <h1 style={{ margin: "0 0 8px 0", fontSize: "28px", fontFamily: "Georgia, serif", color: "var(--plum, #7b1748)" }}>
              Kavach Saathi Support
            </h1>
            <p style={{ margin: 0, color: "var(--muted, #756b70)", fontSize: "14px", lineHeight: "1.5" }}>
              Our support team and security agents are here to protect your transactions and assist you with return verifications.
            </p>
          </div>

          {/* User Status Bar */}
          <div 
            style={{
              background: "var(--pink, #f7e8f0)33",
              border: "1px solid var(--line, #e7e0e3)",
              borderRadius: "12px",
              padding: "12px 16px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "10px",
              fontSize: "13px"
            }}
          >
            <CircleUserRound size={18} style={{ color: "var(--plum, #7b1748)" }} />
            {auth?.user ? (
              <span>
                Logged in as <strong>{auth.user.name}</strong> ({auth.user.role})
              </span>
            ) : (
              <span>Logged out. Log in to track interactions.</span>
            )}
          </div>

          {/* Contact Methods */}
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "10px", padding: "20px 0" }}>
              <LoaderCircle className="spin" size={24} style={{ color: "var(--plum, #7b1748)" }} />
              <span style={{ fontSize: "13px", color: "var(--muted, #756b70)" }}>Fetching contact information...</span>
            </div>
          ) : error ? (
            <div style={{ color: "#e5484d", fontSize: "13px", padding: "10px 0" }}>{error}</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Call Option */}
              <a
                href={`tel:${supportInfo.phone?.replace(/[^+\d]/g, "")}`}
                onClick={() => handleInteraction("call")}
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <div 
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "20px",
                    border: "1px solid var(--line, #e7e0e3)",
                    borderRadius: "16px",
                    padding: "20px",
                    textAlign: "left",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    background: "white",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--plum, #7b1748)";
                    e.currentTarget.style.background = "var(--pink, #f7e8f0)11";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "var(--line, #e7e0e3)";
                    e.currentTarget.style.background = "white";
                  }}
                >
                  <div style={{ color: "var(--plum, #7b1748)", background: "var(--pink, #f7e8f0)", padding: "12px", borderRadius: "12px" }}>
                    <Phone size={24} />
                  </div>
                  <div>
                    <span style={{ display: "block", fontSize: "12px", color: "var(--muted, #756b70)", fontWeight: "600", textTransform: "uppercase" }}>Phone Support</span>
                    <strong style={{ fontSize: "18px", color: "var(--ink, #241b20)" }}>{supportInfo.phone}</strong>
                  </div>
                </div>
              </a>

              {/* Email Option */}
              <a
                href={`mailto:${supportInfo.email}`}
                onClick={() => handleInteraction("email")}
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <div 
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "20px",
                    border: "1px solid var(--line, #e7e0e3)",
                    borderRadius: "16px",
                    padding: "20px",
                    textAlign: "left",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    background: "white",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--plum, #7b1748)";
                    e.currentTarget.style.background = "var(--pink, #f7e8f0)11";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "var(--line, #e7e0e3)";
                    e.currentTarget.style.background = "white";
                  }}
                >
                  <div style={{ color: "var(--plum, #7b1748)", background: "var(--pink, #f7e8f0)", padding: "12px", borderRadius: "12px" }}>
                    <Mail size={24} />
                  </div>
                  <div>
                    <span style={{ display: "block", fontSize: "12px", color: "var(--muted, #756b70)", fontWeight: "600", textTransform: "uppercase" }}>Email Support</span>
                    <strong style={{ fontSize: "18px", color: "var(--ink, #241b20)", wordBreak: "break-all" }}>{supportInfo.email}</strong>
                  </div>
                </div>
              </a>
            </div>
          )}

          {/* Logging indicator */}
          {loggingStatus === "logging" && (
            <div style={{ fontSize: "12px", color: "var(--plum, #7b1748)", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
              <LoaderCircle className="spin" size={14} /> Recording support interaction...
            </div>
          )}
          {loggingStatus === "logged" && (
            <div style={{ fontSize: "12px", color: "var(--green, #137a50)", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
              <Check size={14} /> Interaction recorded successfully.
            </div>
          )}

          {/* Safety Ribbon */}
          <div 
            style={{ 
              display: "flex", 
              alignItems: "center", 
              justifyContent: "center", 
              gap: "8px", 
              fontSize: "12px", 
              color: "var(--green, #137a50)",
              background: "var(--green-soft, #e6f5ed)",
              borderRadius: "8px",
              padding: "10px",
              fontWeight: "600"
            }}
          >
            <ShieldCheck size={16} /> 100% Secure Protected Commerce Channels
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="site-footer" style={{ marginTop: "auto", background: "var(--ink, #241b20)", color: "white", padding: "20px max(20px, calc((100vw - 1280px) / 2))" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <span style={{ fontSize: "13px" }}>© 2026 Kavach Saathi Storefront. All rights reserved.</span>
          <span style={{ fontSize: "13px", opacity: 0.8 }}>Agent-protected commerce support</span>
        </div>
      </footer>
    </div>
  );
}
