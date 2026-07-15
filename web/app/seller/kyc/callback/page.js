"use client";

import { useEffect, useState } from "react";

import { post } from "@/lib/api";

export default function KycCallbackPage() {
  const [status, setStatus] = useState("Completing DigiLocker verification…");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (!code) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reading redirect query params on mount
      setStatus("No authorization code was returned by DigiLocker.");
      return;
    }
    post("/seller/kyc/complete", { code, redirect_uri: window.location.origin + window.location.pathname })
      .then((result) => setStatus(`KYC status: ${result.digilocker_kyc_status}. Redirecting…`))
      .catch((reason) => setStatus(reason.message || "Could not complete DigiLocker verification"))
      .finally(() => {
        window.setTimeout(() => { window.location.href = "/seller"; }, 1800);
      });
  }, []);

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", fontFamily: "sans-serif" }}>
      <p>{status}</p>
    </div>
  );
}
