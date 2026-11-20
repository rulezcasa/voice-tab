# The Expense agent you just talk to


## The problem

Expense trackers and Splitwise fail for one reason: logging is a chore, so you put it off and then forget.

To log one grocery run in Splitwise you have to:

1. Open the app
2. Pick the group
3. Type the description and the amount
4. Pick who's in on it and how it's split
5. Fix the date if it wasn't today

That's five steps of friction for a $40 receipt. So expenses go unlogged, roommates chase each other, and when you later wonder "what was that $20 on Tuesday?" there's nothing to look up.

## The solution

An ambient, voice-first agent. Hit one button and talk:

| You say | Tab does |
| --- | --- |
| "I paid 40 bucks for groceries today, split with my roommates." | Resolves "roommates" to Sam and Priya, splits $40 three ways ($13.34 / $13.33 / $13.33), creates the expense in the Splitwise group "Apt 4B". Sam and Priya get the Splitwise notification. |
| "Spent 20 on a cab." | Logs a personal $20 expense, category Transport, dated today. Nothing goes to Splitwise. |
| "Dinner was 90, me, Sam and Alex." | There are two Alexes in your contacts, so it asks: "Alex Chen or Alex Park?" |
| "Actually the groceries were 45." | Updates the last expense and recalculates the shares. |
| "What did I spend 20 dollars on last Wednesday?" | "A cab: $20 on Wed Nov 12, logged at 6:42 pm." It shows the exact record. |
| "How much have I spent on rides this month?" | Finds cab, Uber and Lyft entries by meaning, not keywords, and returns the total with the rows behind it. |

## Potential Sponsor tools

### Core: Superlinked SIE (all inference)

Tab is built as a harness of small, task-specific models served by SIE, rather than one big LLM doing everything.

Winning critera : Best Personal Agent Harness Using SIE Serverless | Best Technical Build for Personal Agents.**

### Core: SingleStore (memory)

One database for both kinds of question:

- Exact questions ("$20, last Wednesday") are plain SQL filters on amount and date.
- Fuzzy questions ("rides", "roomies") use vector similarity on bge-m3 embeddings, in the same query.

### Optional, if time permits

- Airbyte: sync card transactions (a Google Sheet of exported statements, or Gmail receipts) into SingleStore so Tab can reconcile: "You said $40, but Safeway charged $43.17. Update it?"
- Persona: verify the human behind the agent before it posts expenses that bill other people, and show a "verified human" badge on each Splitwise entry in the audit trail.

## Demo script (3 minutes)

1. Hook (15 s): "Show of hands: who has an unlogged expense right now?"
2. The money shot (45 s): "I paid 40 bucks for groceries today, split with my roommates." Two teammates on stage hold up their phones with the notification. The audit trail fills in live.
3. Personal expense (15 s): "Spent 20 on a cab." It's logged with no split.
4. Clarifying question (30 s): "Dinner was 90 with Sam and Alex." Tab asks "Alex Chen or Alex Park?" We answer "Chen" and it posts.
5. Recall (45 s): "What did I spend 20 dollars on last Wednesday?" → the exact record. Then "How much on rides this month?" → semantic matches and a total.
6. Under the hood (30 s): the audit trail: N small-model calls, each with model, confidence and latency; the SQL that answered the question; the Splitwise API response.

## Pitch lines

"Splitwise is great at the ledger and terrible at the logging. Tab is the logging."

"Small models do the work and every decision leaves a receipt."

https://markdownlivepreview.com
