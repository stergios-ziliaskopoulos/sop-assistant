import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


def _sanitize(text: str) -> str:
    if not text:
        return ""
    return text.encode("utf-8", errors="replace").decode("utf-8")


async def notify_handoff(
    email: str,
    question: str,
    chat_context: str,
    session_id: str | None = None,
    webhook_url: str | None = None,
) -> bool:
    effective_webhook = webhook_url or settings.SLACK_WEBHOOK_URL
    if not effective_webhook:
        return False

    email = _sanitize(str(email or ""))
    question = _sanitize(str(question or ""))
    chat_context = _sanitize(str(chat_context or ""))
    session_id = _sanitize(str(session_id or "N/A"))

    # Last 3 lines of transcript for the Slack message
    lines = [l.strip() for l in chat_context.strip().splitlines() if l.strip()]
    recent = "\n".join(lines[-3:]) if lines else "(no transcript)"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "\U0001f6a8 Human Handoff Requested",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Customer Email:*\n{email}"},
                {"type": "mrkdwn", "text": f"*Session:*\n`{session_id or 'n/a'}`"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Unresolved Question:*\n>{question}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Last Messages:*\n```{recent}```",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "\u23f1\ufe0f SLA: respond within *4 hours*",
                },
            ],
        },
    ]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                effective_webhook,
                json={
                    "text": f"\U0001f6a8 Handoff: {email} — {question[:80]}",
                    "blocks": blocks,
                },
            )
            resp.raise_for_status()
            return True
    except Exception:
        logger.warning("Slack notification failed", exc_info=True)
        return False
