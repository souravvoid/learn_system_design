# learnsystemdesign

TCS-504 high-level design (HLD) case studies implemented as a small, runnable FastAPI service:

1. **Food delivery** (Swiggy/Zomato-like) — order flow, mock payment, real-time delivery tracking.
2. **Notification system** — fan-out through a message queue, channel workers, retries, dead-letter queue.
3. **URL shortener** (Bitly-like) — Base62 key generation, cache-aside reads, 302 redirect, async analytics.

The goal is to make each HLD concrete: the architecture documents in [`docs/hld/`](docs/hld/) describe the production shape, and the code in [`src/`](src/) implements the same flow with local, dependency-free stand-ins for infrastructure.

## Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12+ with type hints | Required by the brief |
| Package/env manager | `uv` | Fast, reproducible local setup |
| API | FastAPI + Pydantic v2 | Request/response schemas are the API contract |
| Database | SQLite via SQLAlchemy 2.x async | Local stand-in for a relational DB |
| Cache | Redis-compatible in-memory store | Same `get/set/delete/incr` surface as Redis; no server needed |
| Message broker | `asyncio.Queue` broker | Stand-in for Kafka/Redis Streams; no external infrastructure |
| Real-time updates | Server-Sent Events (SSE) | Simpler than WebSockets for one-way delivery status |
| Diagrams | Mermaid.js | Rendered directly in GitHub markdown |

## Quick start

```bash
# From the repository root
uv venv --python 3.12
uv pip install -r requirements.txt

# Run the combined API (all three case studies)
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive API schema. With `uv sync` the project metadata in `pyproject.toml` is used instead of `requirements.txt`.

```bash
pytest -q          # tests
ruff check .       # lint
mypy src           # static type check
```

The application uses an **in-memory SQLite database**, so data is reset on every process restart. No Redis server, Kafka cluster, or external API key is required.

## Repository layout

```text
learnsystemdesign/
├── main.py                      # uvicorn entrypoint (assembles all three APIs)
├── pyproject.toml               # uv project metadata + tool configuration
├── requirements.txt
├── docs/
│   ├── hld/                     # functional/NFRs, components, Mermaid diagrams, sources
│   │   ├── food_delivery.md
│   │   ├── notification_system.md
│   │   └── url_shortener.md
│   └── api/                     # exact endpoints with JSON request/response schemas
│       ├── food_delivery_api.md
│       ├── notification_api.md
│       └── url_shortener_api.md
├── src/
│   ├── shared/                  # cache, message broker, database session helpers
│   ├── url_shortener/           # Q3 (implemented first: self-contained read/write paths)
│   ├── notification_system/     # Q2
│   └── food_delivery/           # Q1
└── tests/
    ├── test_url_shortener.py
    ├── test_notification.py
    └── test_food_delivery.py
```

## Where the design comes from

Architecture decisions are limited to the sources named in the brief. The docs cite them per component; no scale figures were invented.

| Source | Used for |
| --- | --- |
| GeeksforGeeks (system design tutorials) | Standard HLD building blocks: load balancer, API gateway, service decomposition, caching, message queues, database choice |
| AlgoMonster (system design methodology) | Translating requirements → components → APIs → data model → bottlenecks; LLD-level class boundaries |
| System Design School (`systemdesignschool.io`) | Read/write path separation for URL shorteners, Base62/KGS collision avoidance, cache-aside, 302 redirect, notification fan-out and back-pressure, geo-indexing for nearby places |
| Engineering blogs (industry patterns) | Exponential backoff with dead-letter queues, idempotency keys, async click analytics, SSE for status streams |

### Scale assumptions

Only the numbers supplied in the assignment brief are used:

- **URL shortener:** 100M DAU, ~1M writes/day, ~100:1 read:write, sub-50 ms redirect target, no collisions.
- **Notification system:** ~100k/sec fan-out bursts, retries for reliability, low latency for critical alerts.
- **Food delivery:** low-latency tracking, strong consistency for orders and payments.

The in-memory broker and SQLite are *local simulation choices*, not production capacity claims.

## Implementation notes / deliberate simplifications

- **URL shortener:** IDs come from an atomic DB sequence (the local stand-in for a Key Generation Service) and are Base62-encoded; a `UNIQUE` constraint is the final collision guard. Reads use cache-aside and the redirect is an explicit HTTP **302** with a `Location` header. Analytics is published to a queue after the redirect decision, so it never blocks the read path.
- **Notification system:** a single event fans out to channel topics after preference filtering. `(idempotency_key, channel)` is unique, so redelivery cannot create duplicate notifications. Failed sends retry with exponential backoff, then move to a dead-letter status in the same history table.
- **Food delivery:** Haversine distance over stored coordinates stands in for PostGIS `GEOGRAPHY` indexing. Payments use a DB transaction plus a unique constraint on `order_id` so a repeated request cannot double-charge. Tracking is an `asyncio` task publishing status transitions over an in-memory pub/sub consumed by an SSE endpoint.
- **Out of scope by design:** user profiles beyond registration/preferences, admin dashboards, real payment/email/SMS/push providers, distributed deployment, and full auth token lifecycle. Login verifies credentials locally; a production system would issue a token at the API gateway.

## Documentation index

- [Food delivery HLD](docs/hld/food_delivery.md) · [API](docs/api/food_delivery_api.md)
- [Notification system HLD](docs/hld/notification_system.md) · [API](docs/api/notification_api.md)
- [URL shortener HLD](docs/hld/url_shortener.md) · [API](docs/api/url_shortener_api.md)
