"""Pluggable delivery channels for changelog digests.

Each channel implements:
    class Channel:
        name: str
        def send(self, content: str, *, fmt: str, meta: dict) -> None:

Channels are loaded from config:

    temporal:
      delivery:
        - type: file
          path: context/changelog/{date}.md
        - type: slack
          webhook_url_env: SLACK_WEBHOOK_URL
          channel: "#dev-changelog"
        - type: email
          smtp_host_env: SMTP_HOST
          to: ["dev-team@example.com"]
          subject: "Daily changelog — {date}"
"""

import logging
from typing import Any, Dict, List, Type

CHANNEL_REGISTRY: Dict[str, Type["Channel"]] = {}

logger = logging.getLogger(__name__)


def register(name: str):
    """Decorator to register a channel class."""
    def deco(cls):
        CHANNEL_REGISTRY[name] = cls
        return cls
    return deco


def load_channels(config: Dict) -> List["Channel"]:
    """Load channel instances from config.

    Args:
        config: Application config dict containing temporal.delivery section.

    Returns:
        List of configured Channel instances.
    """
    delivery_config = config.get("temporal", {}).get("delivery", [])
    channels = []

    for channel_cfg in delivery_config:
        channel_type = channel_cfg.get("type")
        if channel_type not in CHANNEL_REGISTRY:
            logger.warning(f"[Channels] Unknown channel type: {channel_type}")
            continue
        try:
            channel = CHANNEL_REGISTRY[channel_type](**channel_cfg)
            channels.append(channel)
            logger.info(f"[Channels] Loaded channel: {channel.name} ({channel_type})")
        except Exception as e:
            logger.error(f"[Channels] Failed to load channel {channel_type}: {e}")

    return channels


# ── Base Channel ──────────────────────────────────────────────────

class Channel:
    """Base class for all delivery channels."""

    name: str = "base"

    def send(self, content: str, *, fmt: str = "markdown", meta: Dict[str, Any] = None) -> None:
        """Send content via this channel.

        Args:
            content: The rendered digest content.
            fmt: Output format (markdown, html, json, slack_blocks).
            meta: Additional metadata (date, day_type, etc.).
        """
        raise NotImplementedError


def _resolve_template(template: str, meta: Dict[str, Any]) -> str:
    """Resolve a path template with metadata variables.

    Args:
        template: Path template like "context/changelog/{date}.md".
        meta: Metadata dict with keys like 'date', 'week', etc.

    Returns:
        Resolved path string.
    """
    meta = meta or {}
    # Add common variables
    if "date" in meta:
        meta["year"] = meta["date"][:4]
        meta["month"] = meta["date"][5:7]
        meta["day"] = meta["date"][8:10]
    if "week" in meta:
        meta["year"] = meta["week"][:4]
        meta["month"] = meta["week"][5:7]
        meta["day"] = meta["week"][8:10]

    try:
        return template.format(**meta)
    except KeyError as e:
        logger.warning(f"[Channels] Unknown template variable: {e}")
        return template


# ── File Channel ──────────────────────────────────────────────────

@register("file")
class FileChannel(Channel):
    """Write digest to a local file.

    Config:
        type: file
        path: context/changelog/{date}.md  # {date}, {week}, {year}, {month}, {day} supported
    """

    name = "file"

    def __init__(self, path: str, **kwargs) -> None:
        self.path_template = path

    def send(self, content: str, *, fmt: str = "markdown", meta: Dict[str, Any] = None) -> None:
        """Write content to file."""
        meta = meta or {}
        path = _resolve_template(self.path_template, meta)

        from pathlib import Path
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(content, encoding="utf-8")
        logger.info(f"[FileChannel] Written to {path}")


# ── Slack Channel ─────────────────────────────────────────────────

@register("slack")
class SlackChannel(Channel):
    """Send digest to Slack via webhook.

    Config:
        type: slack
        webhook_url_env: SLACK_WEBHOOK_URL  # env var containing the webhook URL
        channel: "#dev-changelog"           # display name for the channel
    """

    name = "slack"

    def __init__(self, webhook_url_env: str, channel: str = "#changelog", **kwargs) -> None:
        self.webhook_url_env = webhook_url_env
        self.channel = channel

    def send(self, content: str, *, fmt: str = "slack_blocks", meta: Dict[str, Any] = None) -> None:
        """Send content to Slack."""
        import os
        webhook_url = os.environ.get(self.webhook_url_env)
        if not webhook_url:
            logger.error(f"[SlackChannel] Missing env var: {self.webhook_url_env}")
            return

        # If content is already JSON (slack_blocks format), send directly
        import json
        try:
            if fmt == "slack_blocks":
                payload = json.loads(content)
            else:
                # For other formats, wrap in a simple Slack message
                payload = {
                    "channel": self.channel,
                    "text": content[:3000],
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": content[:3000]},
                        }
                    ],
                }
        except json.JSONDecodeError:
            payload = {
                "channel": self.channel,
                "text": content[:3000],
            }

        try:
            import urllib.request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                logger.info(f"[SlackChannel] Sent to {self.channel} (status {resp.status})")
        except Exception as e:
            logger.error(f"[SlackChannel] Failed to send: {e}")


# ── Email Channel ─────────────────────────────────────────────────

@register("email")
class EmailChannel(Channel):
    """Send digest via email (SMTP).

    Config:
        type: email
        smtp_host_env: SMTP_HOST
        smtp_port_env: SMTP_PORT            # optional, default 587
        smtp_user_env: SMTP_USER            # optional
        smtp_password_env: SMTP_PASSWORD     # optional
        from_addr: "agent-hub@example.com"
        to: ["dev-team@example.com"]
        subject: "Daily changelog — {date}"
    """

    name = "email"

    def __init__(
        self,
        smtp_host_env: str,
        smtp_port_env: str = "SMTP_PORT",
        smtp_user_env: str = "",
        smtp_password_env: str = "",
        from_addr: str = "agent-hub@example.com",
        to: List[str] = None,
        subject: str = "Daily changelog — {date}",
        **kwargs,
    ) -> None:
        import os
        self.smtp_host = os.environ.get(smtp_host_env, "localhost")
        self.smtp_port = int(os.environ.get(smtp_port_env, "587"))
        self.smtp_user = os.environ.get(smtp_user_env, "") if smtp_user_env else ""
        self.smtp_password = os.environ.get(smtp_password_env, "") if smtp_password_env else ""
        self.from_addr = from_addr
        self.to = to or []
        self.subject_template = subject

    def send(self, content: str, *, fmt: str = "markdown", meta: Dict[str, Any] = None) -> None:
        """Send email."""
        import os
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not self.to:
            logger.warning("[EmailChannel] No recipients configured")
            return

        meta = meta or {}
        subject = self.subject_template.format(**meta) if meta else self.subject_template

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to)

        # Attach plain text version
        msg.attach(MIMEText(content, "plain", "utf-8"))

        # If HTML format, also attach HTML version
        if fmt == "html":
            msg.attach(MIMEText(content, "html", "utf-8"))

        try:
            if self.smtp_port == 465:
                # SSL
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
            else:
                # STARTTLS
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                server.ehlo()
                if self.smtp_port == 587:
                    server.starttls()
                    server.ehlo()

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.sendmail(self.from_addr, self.to, msg.as_string())
            server.quit()
            logger.info(f"[EmailChannel] Sent to {self.to}")
        except Exception as e:
            logger.error(f"[EmailChannel] Failed to send: {e}")
