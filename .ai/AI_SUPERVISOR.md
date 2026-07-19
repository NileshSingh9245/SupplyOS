# AI SUPERVISOR — SupplyOS

## Mission
Continuously analyze operational data and produce **actionable alerts, forecasts, and recommendations** for admins.

## Provider abstraction
All LLM calls go through `app.infrastructure.external.ai_provider.AIProvider` with a single interface:

```python
class AIProvider(Protocol):
    async def analyze(self, *, system_prompt: str, user_prompt: str,
                      max_tokens: int = 800, temperature: float = 0.2) -> str: ...
```

Implementations:
- `ClaudeProvider` (default) via `emergentintegrations.llm.chat.LlmChat` with model `claude-sonnet-4-5-20250929`.
- `OpenAIProvider` (future) — swap by config `AI_PROVIDER=openai`.
- `GeminiProvider` (future) — swap by config `AI_PROVIDER=gemini`.

The rest of the code depends only on the protocol, never on the concrete provider.

## Modules

### Inventory intelligence
- **Dead stock detection**: no `outbound` movement in ≥ 90 days AND `quantity > 0`.
- **Low-stock prediction**: linear regression over 30-day daily outbound; alert if projected days-to-zero ≤ 3.
- **Reorder suggestions**: for each active product, suggest quantity = `avg_daily_outbound × lead_time_days × safety_factor(1.3)`.
- **Overstock**: `quantity / avg_daily_outbound > 90 days`.

### Sales intelligence
- **Peak hour analysis**: aggregate deliveries by hour-of-day over last 30 days.
- **Peak month analysis**: aggregate revenue by month over last 12 months.
- **Customer trends**: identify customers with ≥ 30% MoM revenue growth or decline.

### Finance intelligence
- **Payment risk**: customers with `outstanding / credit_limit > 0.8`.
- **Overdue prediction**: forecast likelihood of ≥ 30-day overdue based on historical payment lag.

### Delivery intelligence
- **Delay prediction**: identify routes with average completion > planned duration + σ.
- **Driver efficiency**: deliveries/hour by partner, flag < 0.5 × team median.

## Alert schema
```json
{
  "category": "inventory | sales | finance | delivery | operations",
  "severity": "info | warning | critical",
  "title": "Tomatoes will run out in 2 days",
  "message": "Based on outbound velocity of 40kg/day and 78kg on hand, projected stockout is 2025-01-15.",
  "action_hint": "Reorder 500kg from Supplier X (lead time 3 days).",
  "resource_type": "product",
  "resource_id": "<uuid>",
  "meta": {"confidence": 0.87}
}
```

## Cron cadence
| Job | Frequency |
|---|---|
| Metrics aggregation | every 15 minutes |
| Rule-based alerts (dead stock, low stock, credit) | every 15 minutes |
| LLM-summarized insights | every 60 minutes |
| Daily digest email | 08:00 tenant TZ |

## LLM prompting
- System prompt states role, output format constraints (JSON), and forbids fabrication.
- User prompt carries **pre-aggregated numerics** — never raw rows. This bounds token usage and prevents hallucination.
- Response must be parseable JSON matching the alert schema. If parse fails, fallback to storing the raw text as an `info` alert flagged for review.

## Replaceability
Every AI feature is behind a feature flag (`AI_FEATURES` env var comma list). Removing a feature = flipping a flag; no schema migrations required.
