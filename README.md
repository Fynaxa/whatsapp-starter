# whatsapp-starter

A minimal, production-shaped skeleton for the WhatsApp Business Cloud API (Meta Graph API).
It receives webhooks safely, sends messages that respect the 24 hour customer service window,
and survives the two things every real integration runs into: duplicate deliveries and rate limits.
Python 3.11+, standard library only, no framework, no build step.

This is not a chatbot and not a campaign tool. It is the layer underneath one, the part that is
boring to write, easy to get subtly wrong, and expensive to debug once messages are in flight.

## Architecture

```
  customer                 Meta Cloud API                    whatsapp-starter
     |                            |                                 |
     |  "Do you have Monday free?"|                                 |
     |--------------------------->|  POST /webhook  (signed)        |
     |                            |-------------------------------->|  signature.verify_signature(raw body)
     |                            |                                 |  dedup.seen_before(message.id)
     |                            |                                 |  window.record_inbound(wa_id, ts)
     |                            |<--------------------------------|  200 EVENT_RECEIVED
     |                            |                                 |
     |                            |  POST /{phone_number_id}/messages
     |                            |<--------------------------------|  client.send_text      (window open)
     |                            |                                 |  client.send_template  (window shut)
     |          reply             |                                 |  retry 429/5xx, exponential backoff
     |<---------------------------|                                 |
     |                            |  status: sent/delivered/read    |
     |                            |-------------------------------->|  errors.describe(code)
     |                            |                                 |
```

```
whatsapp_starter/
  config.py      environment -> Settings dataclass; no secret ever lives in the code
  signature.py   X-Hub-Signature-256, HMAC-SHA256 over the raw request body
  webhook.py     WSGI app: verification handshake, authenticity, idempotent dispatch
  events.py      webhook envelope -> InboundMessage | StatusUpdate
  dedup.py       O_EXCL marker files: one delivery gets processed exactly once
  window.py      the 24 hour customer service window, with persisted state per contact
  client.py      sending, retry policy, exponential backoff, injectable transport
  errors.py      Meta error codes -> sentences an operator can act on
```

## Quickstart

```bash
cp .env.example .env && $EDITOR .env                      # credentials; .env is git-ignored
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
python -m pytest                                          # 67 tests, no network needed
python -m whatsapp_starter serve --port 8000              # expose via a tunnel, register the URL at Meta
python -m whatsapp_starter send 4915112345678 --text "Moin"
```

## The pitfalls this skeleton already solves

The code is small. The value is in which mistakes it makes impossible.

**1. The 24 hour customer service window.** WhatsApp allows free-form messages only within 24 hours
of the customer's last inbound message. After that, only an approved template may reopen the
conversation. Teams usually discover this in production as error 131047, after the message was
already logged as sent. Here the rule lives in `window.py`, the client refuses a free-form send
before it leaves the process, and the boundary is tested at the second: open at 23:59:59, closed at
exactly 24:00:00. Inbound timestamps are persisted per contact and never move backwards, because
webhooks do arrive out of order.

**2. Signature verification over the raw body.** `X-Hub-Signature-256` is an HMAC-SHA256 of the exact
bytes Meta sent. Parse the JSON, re-serialise it, hash that, and every legitimate request fails, which
is why so many integrations end up skipping the check entirely. `webhook.py` reads the raw body once,
verifies it with `hmac.compare_digest`, and only then parses. An unsigned or wrongly signed payload
never reaches a handler.

**3. Idempotency.** Meta guarantees at-least-once delivery and redelivers entire batches until it sees
a 2xx, so the same `message.id` will arrive again. Without deduplication that means a double reply, a
double booking, or a double charge. `dedup.py` claims each id with `O_CREAT|O_EXCL`, which is atomic on
POSIX, so two workers racing on the same delivery cannot both win. Markers expire on a TTL, and a
handler that raises gives its key back so the event can be replayed once the bug is fixed.

**4. Rate limits and retries.** Cloud API throughput limits (130429), pair limits (131056) and platform
blips (131016) are normal traffic, not exceptions. `client.py` retries only what is worth retrying,
backs off exponentially with jitter, honours `Retry-After` when Meta sends one, and gives up after a
bounded number of attempts instead of hammering a number into a quality-rating penalty. A malformed
template is never retried, because a retry only repeats the mistake.

**5. Delivery status and error codes.** `sent`, `delivered`, `read` and `failed` arrive as separate
webhooks for the same message id, so they are deduplicated per state, not per message. Failures carry
a numeric Meta code and nothing else; `errors.py` turns roughly two dozen of the common ones into
sentences that say what to do, so on-call does not start with a search engine.

**6. Answering 200 to authentic payloads.** Once a payload is verified, the receiver always answers
200, even if a handler fails. A 5xx makes Meta redeliver the whole batch, replaying every healthy
event alongside the broken one. Failures are logged and the affected key is released for replay.

## Tests

67 tests, offline by design: the Graph API transport is injected, so responses are faked and the clock
and jitter are frozen. Covered among others: valid signatures accepted and tampered, unsigned and
wrongly prefixed ones rejected; the window opening and closing at the exact boundary, in several
timezones, with naive datetimes refused outright; a redelivered message processed exactly once across
process restarts; a 429 producing a 0.5 / 1.0 / 2.0 second backoff curve, and `Retry-After` overriding
it.

```bash
python -m pytest -v
```

## Scope, and a deliberate omission

There is no bulk send in this repository, and that is a design decision rather than a missing feature.
Since 2 August 2026, Article 50 of the EU AI Act requires that a chatbot discloses that it is an AI
system, and under section 7 of the German Unfair Competition Act (UWG) every promotional WhatsApp
message to a consumer in Germany needs prior, documented consent. A skeleton that makes mass sending
one function call away invites exactly the use that gets a business number rate-limited by Meta and its
operator sued in Germany. This one is built for conversations a customer started: consent is implicit
in the inbound message, the 24 hour window bounds it, and anything outside that window has to go
through a template Meta reviewed. Add opt-in records and an AI disclosure in your first outbound
template when you extend it.

## License

MIT, see `LICENSE`.
