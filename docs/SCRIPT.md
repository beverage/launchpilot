# Three-minute script (D2)

A draft for Imène to rehearse and amend. It follows the video shot list in [SUBMISSION.md](SUBMISSION.md#the-demo-video-three-minutes-mp4), one beat per step, at about 140 words a minute. Every number comes from the app or `python3 evaluate.py` on `main` after A4, A6, A7 and A8; check them on the deployed build before recording, because the database is shared. Press Reset first.

## The script

**0:00 The stake.** Claire runs supply at Maison Aurore, an independent French cosmetics brand. Her Christmas gift set launches on 2 November. Her suppliers announce six weeks and deliver in eight or nine, their minimum orders are high, and planning tools are built for much larger companies. Her spreadsheet says the pumps hold until December.

**0:15 Raw numbers in.** In September, the retailers' order books arrive as raw numbers: Sérum Éclat, 5,670 units ordered against 4,050 forecast. LaunchPilot reads forty percent more demand and puts it in the projection itself.

**0:40 The filler.** 30 September: the contract manufacturer loses capacity a third time. The bottles and pumps are there, but the filling line is not. LaunchPilot fills the gift set first and sees that Sérum Éclat cannot be filled from launch week: 1,107 units, 54,000 euros. Moving the overflow to the second plant saves all of it.

**1:05 The pump.** 1 October: an email in French. The pump supplier will deliver only 12,000 of 20,000. LaunchPilot reads it, and because it remembers that this supplier has been late on every delivery, it says the pumps run out in the week of 9 November, the week after launch, at 91 percent. A planner who reads the same email but trusts the announced lead times sees it on 21 December.

**1:30 The decision.** Doing nothing puts 571,000 euros at risk. A rush order from the backup supplier would land on 23 November, after the gap, so LaunchPilot says so. The best move is allocation: fill the gift set first, 437,000 euros at risk.

**1:55 The memory learns.** Every delivery teaches it. Pompes Atlas promised six weeks; this order took 79 days. Its planning lead time moves from 62 to 63 days, and all fifteen of its deliveries have been late.

**2:15 Real data.** This notice is real: a cardboard-box maker, in receivership since 8 October. For the demo we mapped it to our fictional gift-box supplier, and the screen says so. 12,000 of the 21,000 launch boxes are still on order with them. If that order does not arrive, the gift set runs out on 16 November instead of 14 December, about a million euros more at risk, with no second source.

**2:35 Proof.** Over thirty synthetic worlds, LaunchPilot dates 118 of 120 stockouts within a week. The attentive planner without memory dates 92. Cost and latency per event are on screen, read live.

**2:55 Live and recorded.** Live: the Claude agents, the Kafka streams and the court notices. Recorded: the brand and its history, which we built ourselves.

## Judge Q&A

- **"Is the baseline a strawman?"** No. It reads every email and confirmation the day it arrives, which nobody at a small brand has time to do. The only thing it lacks is the supplier memory: 118 against 92 dated stockouts, and 2 against 28 dates wrong by more than a week.
- **"The data is synthetic?"** Yes, the brand, its history and the scenario; we built them and say so on screen. The court notices and company cards are real public data.
- **"Why is a real company in your demo?"** A labelled demo mapping. The alert only asks what happens if an open order does not arrive. Receivership means the company keeps trading under court supervision; nothing is said about its lead times.
- **"Did you tune the scenario?"** Yes, and every change is logged in DECISIONS.md. The pump order was retuned so the crunch comes from lead-time slippage; the filler's capacity was set so the recorded capacity drops matter; and the proof runs over thirty random worlds from the same generator.
- **"Why an agent and not rules?"** It reads free-text French emails and retailer order books, ignores noise, decides what to compute, and cites the rows behind every alert. The maths are deterministic tools; a rules fallback keeps the demo running without the API.
- **"We already have an ERP and Excel."** They hold the orders. LaunchPilot reads the mailbox and the retailers' order books, remembers how each supplier really delivers, and prices the decision in euros.
- **"What does it cost?"** Cents per live event, shown on the proof tab from the agent-run log; every Claude call goes through our gateway on Aiven, which logs its cost.
- **"What are the limits?"** Planning is in weeks, and a delivery counts for its whole week. Capacity is checked separately from components. Revenue figures are at shelf price.
