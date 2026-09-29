"""Command line: run the webhook, or send a single message."""

from __future__ import annotations

import argparse
import logging
from wsgiref.simple_server import make_server

from .client import WhatsAppClient
from .config import Settings, load_dotenv
from .dedup import DedupStore
from .events import InboundMessage, StatusUpdate
from .webhook import WebhookApp
from .window import WindowTracker

LOGGER = logging.getLogger("whatsapp_starter")


def _on_message(message: InboundMessage) -> None:
    LOGGER.info("inbound %s from %s: %s", message.type, message.wa_id, message.text)


def _on_status(status: StatusUpdate) -> None:
    LOGGER.info("status %s for %s: %s", status.status, status.id, status.explanation or "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whatsapp_starter")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the webhook receiver")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    send = sub.add_parser("send", help="send one message to one recipient")
    send.add_argument("to", help="recipient in E.164 without the plus, e.g. 4915112345678")
    send.add_argument("--text", help="free-form text, only inside the 24 hour window")
    send.add_argument("--template", help="name of an approved template")
    send.add_argument("--language", default="de")
    send.add_argument("--param", action="append", default=[], help="template body parameter")

    args = parser.parse_args(argv)
    if args.command == "send" and not (args.text or args.template):
        parser.error("give either --text or --template")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    settings = Settings.from_env()
    windows = WindowTracker(settings.state_dir / "windows.json")

    if args.command == "serve":
        app = WebhookApp(
            settings=settings,
            dedup=DedupStore(settings.state_dir / "seen"),
            windows=windows,
            on_message=_on_message,
            on_status=_on_status,
        )
        LOGGER.info("listening on http://%s:%s", args.host, args.port)
        make_server(args.host, args.port, app).serve_forever()
        return 0

    client = WhatsAppClient(settings=settings, windows=windows)
    if args.template:
        message_id = client.send_template(args.to, args.template, args.language, args.param)
    else:
        message_id = client.send_text(args.to, args.text)
    LOGGER.info("accepted as %s", message_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
