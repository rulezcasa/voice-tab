# Personal Memory Agent

## One-Line Idea

**An AI agent that remembers the small details of your life that are
easy to forget but unexpectedly useful later.**

Instead of manually organizing notes, lists, and trackers, users can
naturally tell, show, or eventually speak to the agent. The agent
decides what is worth remembering, converts it into structured memory,
updates old memories when circumstances change, and retrieves the right
information when needed.

------------------------------------------------------------------------

## The Problem

Every day, we encounter small pieces of information that are useful
later but not important enough to carefully organize:

-   "I lent Daniel my USB-C hub."
-   "I put my passport in the top desk drawer."
-   "The apartment uses 16x20x1 air filters."
-   "Last time the Wi-Fi broke, restarting the modem fixed it."
-   "I parked on level 4 near elevator B."
-   "I promised Sarah I'd send her the slides."
-   "I liked the spicy ramen at that restaurant."
-   "My bike tires were at 45 PSI last time."

Existing tools are poorly suited to this.

Calendars are for events. Task managers are for actions. Notes apps
require users to intentionally record and organize information. Search
only works if the information was stored somewhere in the first place.

The problem is not that people cannot store information.

**The problem is that most small life details do not feel important
enough to store until the moment we need them.**

------------------------------------------------------------------------

## The Solution

Build a **Personal Memory Agent** that acts as a memory layer for
everyday life.

Users communicate naturally:

> "Alex borrowed my black hoodie today."

The agent recognizes that this could matter later and creates a memory:

``` json
{
  "type": "lent_item",
  "item": "black hoodie",
  "person": "Alex",
  "status": "outstanding",
  "date": "2026-11-18"
}
```

Later:

> "Alex returned my hoodie."

Instead of creating another unrelated note, the agent finds the existing
memory and updates it:

``` text
Black hoodie -> Alex -> returned
```

The user can then ask:

> "Who currently has my stuff?"

The agent retrieves only active lending memories and answers naturally.

------------------------------------------------------------------------

## Core Principle

The user should **not** have to maintain a database.

They should not need forms such as:

``` text
Item: USB-C Hub
Person: Daniel
Transaction: Lent
Date: November 18
Status: Outstanding
```

They simply say:

> "I gave Daniel my USB-C hub."

The agent handles the rest.

The interface is conversation.

The database exists behind the scenes.

------------------------------------------------------------------------

## What Can the Agent Remember?

### 1. Borrowed and Lent Items

> "Mike borrowed my charger."

Stores:

-   Item
-   Person
-   Date
-   Status
-   Optional expected return date

Later:

> "Who has something of mine?"

------------------------------------------------------------------------

### 2. Where Things Are

> "I put my passport in the top drawer."

Stores:

-   Object
-   Location
-   Date last seen
-   Optional photo

Later:

> "Where's my passport?"

------------------------------------------------------------------------

### 3. "Last Time" Knowledge

> "Restarting the modem fixed the Wi-Fi."

Later:

> "What did I do last time the Wi-Fi stopped working?"

The agent retrieves the previous experience instead of giving generic
internet troubleshooting advice.

------------------------------------------------------------------------

### 4. Personal Facts

> "My apartment uses 16x20x1 air filters."

Later:

> "What size air filter do I need?"

------------------------------------------------------------------------

### 5. Commitments

> "I told Maya I'd send her the dataset."

Stores:

-   Person
-   Commitment
-   Date
-   Status

Later:

> "Did I promise anyone anything this week?"

------------------------------------------------------------------------

### 6. Experiences and Preferences

> "I really liked the spicy miso ramen here."

Later:

> "What did I order last time?"

------------------------------------------------------------------------

### 7. Temporary Context

> "I parked on level 4, section C, near elevator B."

This information may be useful for hours rather than years.

The system can distinguish between **short-lived memories** and
**long-term memories**.

------------------------------------------------------------------------

## How Information Enters the Agent

### Text

The simplest MVP.

Users naturally message the agent:

> "Remember that Jake has my drill."

Or, ideally:

> "Jake has my drill."

The agent automatically determines whether the statement is worth
remembering.

### Voice

Voice makes memory capture almost effortless.

A user could say while leaving home:

> "I'm putting the spare key behind the cereal boxes."

The system transcribes the voice and processes it through the same
memory pipeline.

### Photos

A user could photograph a drawer and say:

> "I'm putting my passport here."

The agent stores:

-   The extracted description
-   Relevant objects
-   Location context
-   Original image reference

When asked later, it can return both the answer and the original photo.

### Screenshots

A screenshot might contain useful information such as:

-   Parking confirmation
-   Return deadline
-   Reservation information
-   Someone promising to return an item
-   Instructions worth remembering

The agent extracts the useful information rather than storing only an
unsearchable screenshot.

------------------------------------------------------------------------

## The Interesting AI Problem

The central question is:

> **Is this information likely to be useful to this person later?**

Every user message does not need to become permanent memory.

Example:

> "I'm tired today."

Probably do not store permanently.

But:

> "My landlord said the water shutoff valve is behind the washing
> machine."

Potentially very useful later.

The agent performs a memory-worthiness decision:

``` text
Incoming information
        |
        v
Is this worth remembering?
       / \
     No   Yes
     |     |
Normal    Extract
reply     memory
            |
            v
      New or existing?
          /      \
       New       Existing
        |           |
      Store       Update
```

This decision-making layer is what makes the product an **agent**,
rather than simply a searchable notes application.

