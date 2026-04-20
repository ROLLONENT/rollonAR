# ROLLON AR - Product Vision & Feature Roadmap

## System Status (V35 Audit - 2026-04-16)

**13,376 lines of code | 91 API routes | 16 templates | 5 modules**

---

## v35.6 Release Notes (2026-04-19)

### Mail Merge Export (Directory > Captain only)
Purple "Export to Mail Merge" button ships a Google Sheet compatible with Mail Merge with Attachments (Digital Inspiration) into Drive folder "ROLLON AR Pitches". Modal takes Pitch Name, honours selection vs. current filtered view, supports Works With linked grouping and the older Group by Company toggle, and lets the Captain pick between recipient-local auto-stagger and fixed-timezone send times. The generated sheet matches the 5-column format (First Name, Email Address, Scheduled Date, File Attachments, Mail Merge Status) with a second "Mail Merge Logs" tab left empty for Mail Merge to populate.

**Data behaviour (v36).** Contacts linked via Works With combine into one row first, then contacts at the same MGMT / Label / Publisher combine; 1 = first name greeting, 2 = "Hi A and B" (alt: "Hi both"), 3 = "Hi A, B and C" (alt: "Hi all"), 4+ = "Hi ... and N" (alt: "Hi all"), with emails joined by comma. Scheduled Date emits in America/Los_Angeles (matching the `[Use] Date Time LA to Send Email` column) using the per-contact timezone resolved by `modules/timezone_map.py` (90+ city IANA map + Cities.Timezone aliases + country default).

**Side effects.** Summary row appended to Pitch Log (Status = Ready to Send, URL in DISCO Link column). Each exported contact gets a `Pitched: {Pitch Name}` tag and Last Outreach = today in Personnel. Email sending is out of scope, Celina writes the body in Gmail and runs Mail Merge with Attachments manually.

### Emergency Quick Filter Pills (Directory)
Temporary hardcoded pill row below the toolbar (UK / US / MGMT Only / Writer MGMT / Publishers / Labels / Agents / Dance) to unblock pitching while the universal filter system is broken. Dance uses OR mode across Tags and Genre. Removal targeted for v35.7 once universal filter parity is restored.

---

## TIER 1 - FORCE MULTIPLIERS (10x Celina's output)

### 1. Morning Briefing Dashboard (partially built)
**What:** A single screen at 7am that tells you: 3 songs need admin attention, 2 invoices are overdue, Ben Wylen's release is in 4 days, you haven't reached out to Jamie at Rightsbridge in 22 days, and there's a sync brief due Friday.
**Why:** Every morning starts with 15 minutes of "what was I doing?" across tabs. This eliminates that entirely.
**Effort:** 3 hours (API exists at /api/briefing, needs better frontend + push notification)
**Dependencies:** Dashboard template, notification system

### 2. One-Click Pitch Campaigns
**What:** Select a song, pick "Dance A&R" or "Sync Supervisors," system auto-generates personalized emails for 50 contacts, schedules sends across timezones, logs everything, marks pitched contacts.
**Why:** A pitch campaign currently takes 2-3 hours of manual email composition. This makes it 10 minutes.
**Effort:** 4 hours (pitch_builder.py exists, needs SMTP integration and frontend workflow)
**Dependencies:** SMTP credentials, email templates, pitch contacts tagged in directory

### 3. Auto-Admin Checklist Engine
**What:** When a song moves to "Mastered" status, auto-create admin checklist: ISRC requested, metadata submitted, DSP delivery scheduled, lyric doc generated, playlist updated, social assets requested.
**Why:** Song admin is the most error-prone part. Forgotten ISRC registrations cost real money.
**Effort:** 4 hours (checklist UI exists, needs status-triggered automation)
**Dependencies:** Song status field, checklist template system

### 4. Smart Contact Follow-Up
**What:** System tracks last outreach per contact. Surfaces "cold contacts" (no outreach in 30+ days) grouped by priority. One click to draft personalized follow-up using their last interaction context.
**Why:** Relationships die from neglect. This ensures nobody important goes dark.
**Effort:** 3 hours (follow-up API exists at /api/follow-ups, needs enrichment)
**Dependencies:** Last Outreach field populated, email template integration

### 5. Revenue Pipeline Tracker
**What:** Connect invoice data to artist/project. See: this artist has generated $X in sync fees, $Y in royalties, $Z outstanding. Pipeline shows expected revenue by month.
**Why:** Business decisions need financial context. Which artist is worth investing more in? Which client always pays late?
**Effort:** 6 hours (invoice data exists, needs cross-referencing and visualization)
**Dependencies:** Invoice sheet linked to Personnel, chart library

---

## TIER 2 - COMPETITIVE MOATS (things no other tool can do)

### 6. Song DNA Matching
**What:** Analyze metadata patterns: songs with female vocalist + pop + 120+ BPM have 3x higher sync placement rate. When a new brief comes in for "upbeat female pop," system instantly surfaces the 5 best candidates with match scores.
**Why:** No A&R tool correlates song attributes with placement success. This is genuine intelligence.
**Who it impresses:** Sync supervisors, brand partners, other A&Rs
**Defensibility:** Requires YOUR data (798 songs + pitch history). Can't be replicated without the dataset.

### 7. Relationship Graph
**What:** Visual network showing: this songwriter wrote with that producer who is signed to this label whose A&R you had coffee with last month. Surface hidden connections: "You know Jamie through 3 mutual contacts."
**Why:** Music industry runs on relationships. Seeing the web reveals warm intros you didn't know existed.
**Who it impresses:** Anyone who sees it. Labels, publishers, artists.
**Defensibility:** Built on 5,305 contacts with relationship data. Years to replicate.

### 8. Pitch Analytics Engine
**What:** Track: 200 dance pitches sent, 23 responses, 8 meetings, 2 placements. Show conversion funnel by pitch type, by season, by contact tier. Which email template has the best open rate?
**Why:** No A&R operator measures their conversion. Celina would be the first to quantify her pitch performance.
**Who it impresses:** Potential investors, label partners evaluating her track record.
**Defensibility:** Historical data that only accumulates with use.

### 9. Timezone-Aware Send Scheduling
**What:** When pitching contacts in LA, London, Seoul, and Sydney, system schedules each email to arrive at 9am local time. No more sending Seoul contacts emails at 3am.
**Why:** Email open rates are 40% higher when sent at the right local time.
**Who it impresses:** International contacts who notice the professionalism.
**Defensibility:** Built into workflow, requires timezone data per contact (already tracked in Cities).

### 10. Live Collaboration Rooms
**What:** When working on a song with a remote producer, create a shared workspace: song metadata, admin checklist, split calculator, lyric doc, audio player, all in one link. Producer can update their sections, everything syncs.
**Why:** Current workflow is fragmented across email, WhatsApp, Dropbox, and spreadsheets.
**Who it impresses:** Songwriters and producers who have never seen management this organized.
**Defensibility:** Integrated into the full data system. Standalone tools can't match the context.

---

## TIER 3 - REVENUE GENERATORS (things that make or save money)

### 11. Invoice Automation Suite
**What:** Generate branded PDF invoices, email them with payment links, auto-detect overdue, send graduated reminders (7/14/30 days), mark paid when bank confirms. Monthly report: outstanding, collected, overdue.
**Why:** Late payments are the #1 cash flow problem. Automated reminders recover 30%+ of overdue invoices.
**Revenue impact:** Direct: recover overdue invoices faster. Indirect: professional image = more business.
**Timeline:** 2 days for full automation (PDF generation + SMTP reminders partially built)

### 12. Sync Brief Response System
**What:** Music supervisor sends brief: "Need upbeat indie for Nike campaign, 60s edit, master + pub clearance under $5K." System auto-matches from catalog, generates response package with audio links, clearance info, and pricing.
**Why:** Speed wins sync placements. First to respond with the right song often gets the placement.
**Revenue impact:** Each sync placement = $2K-$50K. Responding 2 hours faster could mean 2-3 more placements per year.
**Timeline:** 1 week (requires Song DNA matching + brief template system)

### 13. Distribution Channel Manager
**What:** One-click send to Rightsbridge (rights registration), sync reps, playlist curators. Track which channels get which songs. Never accidentally send the wrong version.
**Why:** Distribution is currently manual CSV exports and emails. This makes it systematic.
**Revenue impact:** Faster distribution = earlier revenue. Fewer errors = fewer lost royalties.
**Timeline:** 3 days (CSV export partially built, needs SMTP delivery and channel config)

### 14. Productized A&R Dashboard (SaaS potential)
**What:** Strip ROLLON-specific data, make the system configurable. Other A&Rs, managers, and publishers pay $99/month for their own instance.
**Why:** No tool exists that does this. Airtable requires building from scratch. Disco is catalog-only. This is the full operating system.
**Revenue impact:** 10 users = $12K/year. 100 users = $120K/year. Music industry has thousands of potential users.
**Timeline:** 4-6 weeks for multi-tenant version

---

## TIER 4 - DELIGHT (things that make people smile)

### 15. Song of the Day Spotlight
**What:** Dashboard highlights one song each day from the catalog. Shows its story: who wrote it, when, where, admin completion, pitch history. A daily moment of pride in the catalog.
**Emotional impact:** Reminds you why you do this work. Every song has a story.

### 16. Achievement Badges
**What:** "100 pitches sent this month" / "All admin complete for Q2 releases" / "Zero overdue invoices." Subtle celebrations for hitting milestones.
**Emotional impact:** Solo operators never get recognition. The system should notice your wins.

### 17. Beautiful Pitch Decks
**What:** When a brand partner asks "what do you manage?", one click generates a gorgeous visual deck: artist photos, recent placements, streaming stats, press highlights. Dark theme with gold accents matching the system.
**Emotional impact:** "These people are professional. I want to work with them."

### 18. Smart Quick Actions
**What:** After opening a song record, system suggests next actions based on status: "This song is mastered but has no ISRC - register now?" / "Release date is in 5 days - have you submitted to DSPs?"
**Emotional impact:** The system thinks ahead for you. Like having a brilliant assistant who never forgets.

### 19. Writer Session Scheduler
**What:** When planning a writing trip to Nashville, system shows all contacts in Nashville, their availability, recent outreach history, and past songs written together. One click to send session request emails.
**Emotional impact:** Walking into a city feeling completely prepared. Every meeting is warm, not cold.

### 20. Year in Review
**What:** Annual summary: songs written, artists developed, pitches sent, placements landed, revenue generated, contacts added, relationships deepened. Beautiful infographic that tells the story of the year.
**Emotional impact:** Standing proof of progress. Shareable with partners, artists, investors.

---

## Implementation Priority Matrix

| Feature | Impact | Effort | Priority |
|---------|--------|--------|----------|
| Fix broken overnight commits | CRITICAL | 4h | NOW |
| Morning Briefing | HIGH | 3h | Day 2 |
| One-Click Pitch | HIGH | 4h | Day 3 |
| Invoice Automation | HIGH | 2d | Day 4 |
| Auto-Admin Checklist | HIGH | 4h | Day 5 |
| Smart Follow-Up | HIGH | 3h | Week 1 |
| Distribution Channels | MEDIUM | 3d | Week 1 |
| Song DNA Matching | HIGH | 1w | Week 2 |
| Pitch Analytics | HIGH | 1w | Week 2 |
| Relationship Graph | MEDIUM | 1w | Week 3 |
| Revenue Pipeline | MEDIUM | 6h | Week 3 |
| Sync Brief Response | HIGH | 1w | Week 3 |
| Productize Evaluation | MEDIUM | 2w | Week 4 |
