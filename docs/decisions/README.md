# Architecture Decision Records

One record per decision that constrains future work. Each states the context, the decision,
the consequences, and the evidence in the repository. Records describe what is implemented;
if the code diverges from a record, the record is out of date and must be revised.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-ema-alpha-0.15.md) | Competency estimate is a per-interview EMA with α = 0.15 | Accepted |
| [0002](0002-http-only-cookie-sessions.md) | Sessions use opaque tokens in HttpOnly cookies, not JWTs in storage | Accepted |
| [0003](0003-static-reviewed-question-bank.md) | Questions come from a reviewed static bank, not runtime generation | Accepted |
| [0004](0004-guest-access-without-claiming.md) | Guests keep id-based access; guest history is never claimed | Accepted |
| [0005](0005-candidate-aware-cooldown.md) | Question cooldown is scoped by candidate and topic | Accepted |

Adding a record: copy the structure of an existing file, number it sequentially, and link it
from this table. Keep it short; the implementation is the detailed reference.
