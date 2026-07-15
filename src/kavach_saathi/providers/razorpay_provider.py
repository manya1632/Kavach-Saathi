from __future__ import annotations

from typing import Any

from kavach_saathi.config import Settings


class RazorpayUnavailable(RuntimeError):
    pass


class RazorpayClient:
    """Thin wrapper over Razorpay's sandbox/test-mode API (final target plan.md's
    payment row names Razorpay first). Real order creation + signature verification --
    no fixture shortcut. Config-gated on RAZORPAY_KEY_ID/SECRET; callers must catch
    RazorpayUnavailable and fall back to COD honestly rather than fake a payment.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.razorpay_key_id and self.settings.razorpay_key_secret)

    def _client(self):
        if not (self.settings.razorpay_key_id and self.settings.razorpay_key_secret):
            raise RazorpayUnavailable("RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not configured")
        import razorpay

        return razorpay.Client(auth=(self.settings.razorpay_key_id, self.settings.razorpay_key_secret))

    def create_order(self, *, amount_rupees: float, receipt: str) -> dict[str, Any]:
        client = self._client()
        order = client.order.create(
            {
                "amount": round(amount_rupees * 100),
                "currency": "INR",
                "receipt": receipt,
                "payment_capture": 1,
            }
        )
        return order

    def verify_payment_signature(
        self, *, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
    ) -> bool:
        client = self._client()
        try:
            client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": razorpay_order_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_signature": razorpay_signature,
                }
            )
            return True
        except Exception:
            return False
