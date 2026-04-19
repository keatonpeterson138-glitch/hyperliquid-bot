"""Email notification module – sends alerts when positions open/close."""
from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends trade notification emails via SMTP (Gmail, Outlook, etc.)."""

    def __init__(
        self,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        sender_email: str = "",
        sender_password: str = "",
        recipient_email: str = "",
        enabled: bool = False,
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipient_email = recipient_email or sender_email
        self.enabled = enabled

        if self.enabled and self.sender_email:
            logger.info(f"Email notifier enabled → {self.recipient_email}")
        else:
            logger.info("Email notifier disabled")

    # ── Public API ──────────────────────────────────────────────
    def notify_open(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        entry_price: float,
        leverage: int,
        sl_pct: float,
        tp_pct: float,
        reason: str = "",
        slot_id: int | None = None,
    ):
        """Send an email when a position is opened."""
        slot_label = f" (Slot {slot_id})" if slot_id is not None else ""
        subject = f"📈 {side} Opened: {symbol}{slot_label}"

        sl_price = entry_price * (1 - sl_pct / 100) if side == "LONG" else entry_price * (1 + sl_pct / 100)
        tp_price = entry_price * (1 + tp_pct / 100) if side == "LONG" else entry_price * (1 - tp_pct / 100)

        body = f"""
<html><body style="font-family: Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 20px;">
<div style="max-width: 500px; margin: 0 auto; background: #161b22; border-radius: 8px; padding: 24px; border: 1px solid #30363d;">
  <h2 style="color: {'#3fb950' if side == 'LONG' else '#f85149'}; margin-top: 0;">
    {'📈' if side == 'LONG' else '📉'} {side} Position Opened
  </h2>
  <table style="width: 100%; border-collapse: collapse; color: #e6edf3;">
    <tr><td style="padding: 8px 0; color: #8b949e;">Symbol</td><td style="padding: 8px 0;"><b>{symbol}</b></td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Direction</td><td style="padding: 8px 0; color: {'#3fb950' if side == 'LONG' else '#f85149'};"><b>{side}</b></td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Entry Price</td><td style="padding: 8px 0;">${entry_price:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Position Size</td><td style="padding: 8px 0;">${size_usd:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Leverage</td><td style="padding: 8px 0;">{leverage}x</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Stop Loss</td><td style="padding: 8px 0; color: #f85149;">{sl_pct}% → ${sl_price:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Take Profit</td><td style="padding: 8px 0; color: #3fb950;">{tp_pct}% → ${tp_price:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Reason</td><td style="padding: 8px 0;">{reason}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Time</td><td style="padding: 8px 0;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
  </table>
</div>
</body></html>
"""
        self._send(subject, body)

    def notify_close(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float | None = None,
        reason: str = "",
        slot_id: int | None = None,
    ):
        """Send an email when a position is closed."""
        slot_label = f" (Slot {slot_id})" if slot_id is not None else ""
        pnl_str = f"${pnl:+,.2f}" if pnl is not None else "--"
        pnl_color = "#3fb950" if (pnl or 0) >= 0 else "#f85149"
        emoji = "✅" if (pnl or 0) >= 0 else "🔴"
        subject = f"{emoji} {side} Closed: {symbol}{slot_label}  {pnl_str}"

        change_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
        if side == "SHORT":
            change_pct = -change_pct

        body = f"""
<html><body style="font-family: Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 20px;">
<div style="max-width: 500px; margin: 0 auto; background: #161b22; border-radius: 8px; padding: 24px; border: 1px solid #30363d;">
  <h2 style="color: {pnl_color}; margin-top: 0;">
    {emoji} Position Closed
  </h2>
  <table style="width: 100%; border-collapse: collapse; color: #e6edf3;">
    <tr><td style="padding: 8px 0; color: #8b949e;">Symbol</td><td style="padding: 8px 0;"><b>{symbol}</b></td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Direction</td><td style="padding: 8px 0;">{side}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Entry Price</td><td style="padding: 8px 0;">${entry_price:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Exit Price</td><td style="padding: 8px 0;">${exit_price:,.2f}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Change</td><td style="padding: 8px 0; color: {pnl_color};">{change_pct:+.2f}%</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">P&L</td><td style="padding: 8px 0; color: {pnl_color}; font-size: 18px;"><b>{pnl_str}</b></td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Reason</td><td style="padding: 8px 0;">{reason}</td></tr>
    <tr><td style="padding: 8px 0; color: #8b949e;">Time</td><td style="padding: 8px 0;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
  </table>
</div>
</body></html>
"""
        self._send(subject, body)

    def send_test(self) -> tuple[bool, str]:
        """Send a test email. Returns (success, message)."""
        if not self.enabled or not self.sender_email:
            return False, "Email notifications not enabled."
        subject = "🤖 Hyperliquid Bot – Test Email"
        body = f"""
<html><body style="font-family: Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 20px;">
<div style="max-width: 500px; margin: 0 auto; background: #161b22; border-radius: 8px; padding: 24px; border: 1px solid #30363d;">
  <h2 style="color: #58a6ff; margin-top: 0;">🤖 Test Email</h2>
  <p>Your Hyperliquid trading bot email notifications are working!</p>
  <p style="color: #8b949e;">Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>
</body></html>
"""
        return self._send(subject, body)

    # ── Internal ────────────────────────────────────────────────
    def _send(self, subject: str, html_body: str) -> tuple[bool, str]:
        """Send an email in a background thread so it doesn't block the bot."""
        if not self.enabled or not self.sender_email:
            return False, "Disabled"

        def _worker():
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = self.sender_email
                msg["To"] = self.recipient_email
                msg.attach(MIMEText(html_body, "html"))

                ctx = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15) as server:
                    server.ehlo()
                    server.starttls(context=ctx)
                    server.ehlo()
                    server.login(self.sender_email, self.sender_password)
                    server.sendmail(self.sender_email, self.recipient_email, msg.as_string())

                logger.info(f"Email sent: {subject}")
            except Exception as e:
                logger.error(f"Email send failed: {e}")

        t = threading.Thread(target=_worker, daemon=True, name="email-send")
        t.start()
        return True, "Sending..."
