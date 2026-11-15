# Grok Bot by xAI: A Comprehensive Research Paper on Architecture, Capabilities, and Enterprise Integration

**Authors:** Research Division, Foundational AI  
**Date:** October 2026  
**Version:** 1.0  
**Source Documentation:** https://docs.x.ai/grok-bot/overview

---

## Abstract

This paper presents a comprehensive analysis of Grok Bot, a persistent AI agent platform launched by xAI in partnership with Cursor. Unlike conventional chatbot interfaces that reset context with each session, Grok Bot introduces durable AI teammates — named Bots with persistent memory, dedicated cloud computers, and the ability to operate real applications autonomously. This paper examines the platform's architecture, capabilities, security model, pricing structure, integration patterns, and enterprise governance features based entirely on official documentation. We evaluate Grok Bot's positioning within the broader AI agent landscape and identify its optimal use cases, operational boundaries, and implications for enterprise AI adoption.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Platform Architecture](#2-platform-architecture)
3. [Core Capabilities](#3-core-capabilities)
4. [Getting Started & Setup](#4-getting-started--setup)
5. [Bot Management & Configuration](#5-bot-management--configuration)
6. [Communication & Collaboration](#6-communication--collaboration)
7. [Skills, Routines & Automation](#7-skills-routines--automation)
8. [Use Cases & Application Domains](#8-use-cases--application-domains)
9. [Security Model & Governance](#9-security-model--governance)
10. [Enterprise & Teams Features](#10-enterprise--teams-features)
11. [Pricing & Plans](#11-pricing--plans)
12. [Platform Support & Mobile](#12-platform-support--mobile)
13. [X (Twitter) Integration](#13-x-twitter-integration)
14. [Limitations & Considerations](#14-limitations--considerations)
15. [Comparative Analysis](#15-comparative-analysis)
16. [Conclusion](#16-conclusion)

---

## 1. Introduction

### 1.1 Background

The AI agent landscape has evolved from single-turn question-answering systems to increasingly autonomous agents capable of executing multi-step workflows. However, most AI assistants operate in ephemeral sessions — context is lost, tool access must be re-established, and the human operator remains the central router for every task. Grok Bot, developed by xAI and integrated with Cursor's infrastructure, represents a departure from this pattern.

### 1.2 What is Grok Bot?

Grok Bot is a product that provides persistent AI teammates ("Bots") with names, assigned roles, and accumulating context. Each Bot operates on a cloud computer equipped with a browser, filesystem, and terminal, allowing tasks to execute in real tools rather than remaining as chat drafts. Users interact with Bots via messaging — typing, dictating, or voice chat — providing a task, relevant context, and tool access. Bots handle multi-step work across apps and websites, send updates (including voice memos and drafts requiring approval), and return when human sign-off is needed.

### 1.3 Key Differentiators

Grok Bot distinguishes itself from conventional AI assistants through five architectural decisions:

1. **Persistent Cloud Computer per Bot**: Each Bot runs on a persistent cloud computer with browser, filesystem, and terminal. Bots use connectors where available and computer use for everything else. Work continues even when the user's laptop is closed.

2. **Setup via Messaging, Not Workflow Builders**: Creating a Bot involves describing the job in a message and granting access as requested. The same Bot is accessible from both desktop and mobile apps.

3. **Inter-Bot Coordination**: Bots can run in parallel, message each other, share context in group chats, and pass task ownership between themselves, removing the user as the bottleneck and router.

4. **Learning Workflows from Demonstration**: Users can walk a Bot through a multi-step process once; the Bot saves it as a "skill" and can rerun it on a schedule.

5. **Compounding Context**: A named Bot retains its memory, files, browser sessions, and preferences across sessions instead of resetting on every task.

---

## 2. Platform Architecture

### 2.1 The Shared Computer Model

The foundational architectural decision in Grok Bot is the shared computer model. All Bots under a single account share one cloud computer, including files, browser sessions, and app logins. This design enables handoffs between Bots without repeating setup. The computer belongs to the user's account, not to any individual Bot. Anything placed on the computer is available to every Bot the user runs.

Between different users, isolation is strict. Each user's work executes on a dedicated Firecracker microVM with hardware-level separation from other users. The four security principles governing the architecture are:

1. **Per-user isolation** — dedicated Firecracker microVM with hardware-level separation
2. **No access by default** — Bots use only the accounts and plugins the user or team grants
3. **Human approval gates** — sensitive actions require approval, evaluated by Auto Review
4. **Administrative control** — admins set rules, delegation, templates, and execution ceilings

### 2.2 System Layers

The platform is organized into six distinct layers:

| Layer | Description |
|-------|-------------|
| **Local Machine** | Chat, review, and approvals on the member's device; optional local execution with per-command approval as default |
| **Environment** | One persistent Firecracker microVM per user; all Bots share that computer |
| **The Bot** | Shell, browser, and computer use inside the hosted computer; no access by default; hands login/2FA/payment steps to the member |
| **Plugins** | Team's Cursor MCP policy applies; OAuth tokens stay on Cursor's connector backend; Bots invoke tools without receiving tokens |
| **Cloud Agents** | Delegates coding tasks to separate computers under existing Cloud Agent controls; admins can disable |
| **Models and Data** | Cursor manages model selection; Privacy Mode means no training on customer data |

### 2.3 Screen Architecture

Each Bot gets its own screen on the shared computer. Multiple Bots can use browser and desktop tools in parallel. A single Bot can only run one computer-use task on its screen at a time. Screens are described as "separate work surfaces, not separate security boundaries."

### 2.4 Filesystem

The shared workspace path is `/workspace`. Users should instruct Bots to keep durable project files there using clear project folders. Files, browser state, and supported sign-ins are designed to survive normal computer updates and recovery. Temporary directories, manually installed packages, and uncommitted application state should be treated as replaceable. Important results should be copied to the shared workspace or attached to the conversation.

### 2.5 Background Operation

Work runs on the cloud computer. Closing the app, the user's laptop, or phone does not stop a background turn or a routine. This is a fundamental architectural property — the cloud computer is the execution environment, and the client apps (desktop, mobile) are thin clients for chat, review, and approvals.

### 2.6 Update, Recovery, and Reset

The platform provides three maintenance operations:

- **Recovery**: Appears only when the computer is unreachable from an error state. The confirmation dialog labels it "Recover Grok Bot's Computer." Recovery is not available from Settings.
- **Update** (Settings → Updates → Grok Bot's Computer): Installs the latest software while keeping files in place.
- **Reset** (Settings → Updates → Grok Bot's Computer): Rebuilds from the last saved snapshot; very recent changes may be lost.

Users should wait for active work to finish before recovery when possible.

---

## 3. Core Capabilities

### 3.1 Computer Use

Bots operate on their cloud computer using a combination of structured connectors and direct computer use (browser interaction, terminal commands, file operations). When a connector is available for a service, it provides a more reliable interface than browser-based interaction. When no connector exists, the Bot falls back to browser automation.

The Bot can:
- Navigate websites and web applications
- Execute shell commands
- Read and write files
- Interact with browser-based tools
- Fill forms and complete multi-step web workflows

Sites may block automation, expire sessions, or require human steps. In such cases, the Bot hands those steps back to the user via the takeover mechanism.

### 3.2 Human Takeover

When a Bot encounters an authentication wall, CAPTCHA, or payment step, it requests manual intervention. The procedure is:

1. Open "Agent Computer" from within the conversation
2. Select the takeover control
3. Manually enter the password, passkey, two-factor code, or complete the CAPTCHA
4. Return control to the Bot

The browser session persists on the shared Grok Bot computer, meaning other Bots can reuse the same authenticated session when appropriate. Users should avoid pasting passwords or one-time codes into chat. For supported connections presenting a secure secret request, users enter the value directly — the value is masked and is not added to the conversation.

### 3.3 Connectors (App Connections)

Connectors provide Bots a structured way to work with supported services. They are installed as plugins from Marketplace:

1. Open Marketplace from the sidebar
2. Browse available plugins
3. Choose "Add"
4. Complete authentication in the browser if requested
5. In chat, type `@` to attach the connector to a task; type `/` to reference a saved skill

Connectors are preferred over browser-based interaction when available — they are often more reliable than clicking through a website. Installed connectors are account-wide, not isolated to one Bot.

### 3.4 X (Twitter) Capabilities

Without signing in (read-only, no account connection needed):
- Search posts
- Open a post from its link
- Read an account's posts and mentions
- See who quoted or reposted a post
- Count recent posts on a topic
- Check trends and news

With the X plugin installed (requires sign-in via Marketplace):
- Access DMs, bookmarks, home timeline, and like data

### 3.5 Bot Memory

Bots retain stable preferences, role context, and summaries of prior work. Conversations and learned context are per-Bot. Shared files, browser sessions, and direct handoffs move context between Bots. Memory is explicitly not a substitute for an authoritative source — for consequential decisions, users should ask the Bot to verify current sources rather than relying on memory alone.

### 3.6 File Handling

Users can attach files via the attachment control, drag-and-drop into the composer, or by pasting images and links directly.

**Supported input formats:**
- Media: Images, audio, and video
- Documents: PDF and plain-text
- Office: Word, Excel, and PowerPoint
- Data/Code: CSV, JSON, YAML, and source-code files
- Web/Email: HTML and email files
- Notebooks: Jupyter notebooks

**Limits:**
- Desktop composer: up to 6 attachments per message
- Documents, images, audio: max 25 MB each
- Video: max 200 MB
- Files that are large, encrypted, damaged, or unusual may fail to be read

### 3.7 Voice Features

Grok Bot supports three voice interaction modes:

1. **Dictation**: Select "Start voice input" in the composer or press `Cmd/Ctrl+D`. Spoken words are transcribed into the composer for editing before sending.
2. **Voice Chat (Live)**: Initiated by choosing "Start voice chat" when the composer is empty. Enables real-time spoken conversation with a Bot.
3. **Voice Memos**: Bots can respond with voice memos embedded in conversations. Users can play, pause, and read transcripts of voice memos.

### 3.8 Draft Review

When a Bot prepares an email or Slack message, an editable draft appears in the conversation. Users review recipients and body, then choose "Send email"/"Send message" or "Discard." This ensures human oversight over all external communications.

---

## 4. Getting Started & Setup

### 4.1 Prerequisites

Users need one of the following plans:
- Any paid individual Cursor plan
- The Cursor Teams plan
- An individual SuperGrok, SuperGrok Plus, or SuperGrok Heavy subscription linked to a Cursor account

Additional requirements include the Grok Bot desktop application (available for macOS, Windows, or Linux) and an app or website where the first Bot can perform real work.

**Privacy Warning**: Grok Bot requires cloud data storage. Accounts using Legacy Privacy Mode must move to a supported Cursor data setting before Grok Bot will function.

### 4.2 Installation

Downloads are available at x.ai/bot.

**macOS**: Select Apple silicon or Intel download. Open the disk image, drag Grok Bot into Applications, and launch. To determine architecture: Apple menu → About This Mac — a "Chip" field indicates Apple silicon; a "Processor" field indicates Intel.

**Windows**: Select x64 or Arm64 download. Run the installer and launch from the Start menu. Architecture check: Settings → System → About → System type.

**Linux**: Builds ship with every stable release under "More downloads." Available formats:
- `.deb` — for Debian and Ubuntu
- `.rpm` — for Fedora and RHEL
- AppImage — for other distributions

Architecture check: run `uname -m` in a terminal. `x86_64` = x64; `aarch64` = Arm64.

Grok Bot checks for updates automatically. Manual checking is available via Settings → Updates → "Check for Updates."

### 4.3 Authentication

1. Click "Sign in" on the welcome screen (or "Sign In with Cursor" from Settings)
2. Complete authentication in the browser window
3. Return to Grok Bot once the browser confirms sign-in
4. SuperGrok subscribers should link when prompted

Authentication uses the user's Cursor account. Organizations requiring SSO complete their normal SSO flow. On initial launch, Grok Bot introduces three concepts: Bots, the shared computer, and routines, then asks which tools the user works with. These answers influence initial teammate suggestions but do not connect or modify those tools.

### 4.4 Creating a First Bot

Users can pick a suggested teammate from the onboarding screen or choose "Create your own" and provide:
- A short name
- One primary job
- A description of how it should work

**Example configuration:**
- **Name:** Piper
- **Job:** Product performance
- **Description:** Investigate product-performance questions using observability tools. Preserve links and screenshots, keep evidence separate from hypotheses, return a short summary prioritizing the highest-impact issue. Never change production settings.

The documentation emphasizes that focused Bots build more useful context than one catch-all Bot.

### 4.5 Anatomy of a Strong Request

A well-constructed request includes five elements:

1. **Outcome** — What should be finished?
2. **Sources** — Which apps, websites, files, or conversations are relevant?
3. **Constraints** — What must the Bot avoid or ask about before doing?
4. **Deliverable** — What form should the output take?
5. **Review point** — When should the Bot pause for human review?

---

## 5. Bot Management & Configuration

### 5.1 Definition

A Bot is a durable AI teammate with a name, a job, its own conversation, and working context that develops over time. A distinct Bot should be created when work has a separate goal or area of ownership, set of tools and sources, working style, approval boundary, or recurring schedule.

### 5.2 Naming Conventions

Recommended job-style names: Talent Scout, Expense Manager, Bug Reproduction. Vague names like "General Helper" are discouraged because they give the Bot less guidance and make its saved context harder to reuse.

### 5.3 Role Descriptions

Roles should be described in operational terms. The description is for persistent rules (e.g., "Never send external messages without approval"), while messages are for task-specific instructions (e.g., "Draft follow-ups for these twelve accounts").

### 5.4 Creating a Bot

1. Select New in the sidebar or use `Cmd/Ctrl+N`
2. Under New chat, pick "Create new Bot" or type a name and select "Create [name] Bot"
3. Use the Bot menu or "Edit Profile" to configure name, label, description, and avatar
4. Begin conversing with a concrete task

### 5.5 Bot Organization

- **Pin**: Keeps active Bots at the sidebar top
- **Hide from sidebar**: Removes from the main list without deleting work — hiding does not pause the Bot or its routines
- **Unhide**: Accessed via "Hidden Bots" at the sidebar bottom

### 5.6 Duplicating a Bot

Duplication replicates a role with different scope (e.g., one Account Health Bot per region).

**What copies:** Profile, settings, enabled skills, routines, avatar  
**What does not copy:** Conversation history, learned memory, chat attachments

### 5.7 Sharing a Bot

Users can create templates for sharing:

1. Open Share menu → Create template
2. Set access: Public link or Team-only (Enterprise accounts default to Team-only)
3. Recipients open a preview on x.ai and choose "Add to Grok Bot"

A public link shows the Bot's shared configuration, including its identity, description, skills, and routines. Users must remove API keys, internal URLs, customer data, and sensitive information before sharing. Adding a shared Bot creates a copy on the recipient's account — it does not give them the user's computer, logins, or conversation history.

Shared Bots are created by other users, not by xAI. Adding one requires accepting third-party bot terms at x.ai/legal/bot-sharing-terms.

### 5.8 Deleting a Bot

Deletion removes the Bot's active profile, conversation, and routines from Grok Bot. However, shared computer files and sign-ins are not isolated by Bot and may remain on the computer. Backend retention follows applicable Cursor terms. Hiding is recommended if future access may be needed.

### 5.9 Bot Coordination & Context Sharing

Bots have separate roles and conversations, but they share the computer. Context passing happens through direct messages, group chats, and shared files. The recommended approach starts with the smallest useful roster:

1. Give one Bot end-to-end ownership of an outcome
2. Add another only for a stable specialist role
3. Use a group chat when handoff visibility matters
4. Keep external actions behind a clear approval boundary

---

## 6. Communication & Collaboration

### 6.1 Messaging Modes

Within a conversation, users can:
- Send text messages
- Paste text, links, and images
- Attach local files
- Dictate via "Start dictation"
- Start voice chats
- Play voice memos from Bots
- Reference saved skills with `/`
- Mention Bots, groups, routines, or connectors with `@`
- Reply to specific messages and react to messages
- Send additional instructions while work is already underway

### 6.2 Redirecting Work in Progress

A direct message from the user takes priority over background work and can redirect the current turn. Sending "Stop now" halts work immediately but does not undo actions the Bot already completed.

### 6.3 Group Chats

Groups serve situations where several Bots need one shared outcome and visible handoffs.

**Creating a group:**
1. Choose New in the sidebar
2. Select two to six Bots in the New chat panel
3. Open the group and optionally rename it
4. Describe the shared outcome and who owns the next step

**Directing messages in groups:**
- Writing normally lets participating Bots decide who responds
- `@`-mentioning a specific Bot assigns ownership of a request
- Using Reply on a Bot's message directs the answer to that Bot
- `@everyone` should be used sparingly for group-wide updates

**Limitations in groups:** Approval requests, secret and login requests, and email or Slack drafts are not available in group chats. Bot-to-group handoffs are currently text-only.

### 6.4 Bot-to-Bot Handoffs (Asynchronous)

A Bot can send an asynchronous message to another Bot. The receiving Bot wakes, handles the request, and can reply later. Handoffs are visible in the conversation. This is ideal when one Bot owns a source system while another owns the deliverable, when a specialist should review a draft, or when a blocker belongs to another role.

### 6.5 Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Search palette | `Cmd/Ctrl+K` |
| Search Bots | `Cmd/Ctrl+Shift+F` |
| New Bot/chat | `Cmd/Ctrl+N` |
| Find in chat | `Cmd/Ctrl+F` |
| Focus prompt | `Cmd/Ctrl+I` or `Cmd/Ctrl+L` |
| Dictate | `Cmd/Ctrl+D` |
| Send | `Enter` or `Cmd/Ctrl+Enter` |
| New line | `Shift+Enter` |

---

## 7. Skills, Routines & Automation

### 7.1 Core Concepts

Grok Bot's automation framework rests on two building blocks:
- **Skill**: A reusable instruction set describing how to accomplish a task
- **Routine**: A directive telling a Bot when to execute a workflow — either on a schedule or triggered by an event

The recommended progression: start with a one-off task, make it reliable, save it as a skill, then automate via routine.

### 7.2 Skills in Detail

A skill encodes steps, decision logic, expected outputs, and safety constraints. Skills are shared across all Bots, though a Bot may need the relevant connector or login to use one.

**Anatomy of a useful skill (six required components):**
1. When to use it
2. Required inputs and access
3. The sequence of work
4. How to validate the result
5. What to return
6. What requires approval

Skills are saved by asking the Bot directly after completing a successful task. They are accessed by typing `/` in the desktop composer. Skills are stored in a "private skills" library shared by all Bots.

### 7.3 Teaching by Demonstration

When the "Teach a task" feature is available, users can show the Bot a browser workflow visually:

1. Open a one-to-one Bot conversation and its computer view
2. Select "Teach a task"
3. Describe the intended result before demonstrating
4. Perform the workflow once
5. Stop recording and review the generated skill
6. Test on a safe example before scheduling

Recordings last up to ten minutes. Microphone audio is not recorded. The result is a draft skill — users must manually add decision rules, failure handling, and approval boundaries not obvious from one example. This feature may be enabled gradually.

### 7.4 Routines

Routines are created by asking the owning Bot directly. Key elements to confirm when creating a routine:
- The owning Bot
- Schedule and time zone
- Input source
- Expected result
- Approval boundary
- Behavior when a source is missing

**Operational limits:**

| Constraint | Value |
|------------|-------|
| Max routines per Bot | 50 |
| Recent run records kept per routine | 20 |
| Minimum interval between schedules | 5 minutes |

Background routines can run while the user's laptop is closed. Deleting a routine is immediate with no undo. Deleting a Bot also removes all routines it owns.

**Inactivity safeguard:** Grok Bot may ask whether to keep routines running after a long period away and pause them if there is no response.

### 7.5 Event-Triggered Routines

Cursor account integrations can start a routine from an event — examples include Slack messages or GitHub notifications. These integrations are separate from Slack/GitHub plugins and may need their own connection flow. The documentation strongly advises defining narrow matching rules and clear response actions, explicitly warning against broad listeners such as "every new message."

### 7.6 Testing

The Test run feature performs real work — it can navigate websites, change files, and call connected tools. Users should use safe inputs and keep write actions behind approval gates.

**Review checklist after testing:**
- Whether current inputs were selected
- Whether output matches the required format
- Whether every action has a source or audit trail
- Whether it stopped at the intended approval point
- Whether failure states are explicit

### 7.7 Trust-Oriented Design Principles

1. Automate preparation before execution — draft, reconcile, or recommend first
2. Require approval for sending, purchasing, deleting, publishing, or changing production systems
3. Include a no-data and stale-data policy
4. Make retries idempotent where possible
5. Tell the Bot where to report partial completion
6. Re-test after any website, connector, or source format change

---

## 8. Use Cases & Application Domains

The documentation prescribes that effective Grok Bots should "own a repeatable outcome, not a loose category of questions." The recommended workflow: begin with read-and-prepare tasks, review output, then layer in approved actions or routines.

### 8.1 Sales Outbound

**Ownership:** Account research, contact prioritization, and review-ready outreach  
**Connected systems:** CRM, product-intent sources, company websites, email, professional networks  
**Starter prompt pattern:** Research CRM accounts, score against ICP and intent signals, identify contacts, draft outreach matching style examples. Skip anyone already in active sequences. Return a review list; do not send or enroll anyone.  
**Progression:** Once output proves reliable, set up a nightly research routine that halts at the review list stage.

### 8.2 Talent Scout

**Ownership:** Sourcing, candidate research, outreach drafts, and scheduling preparation  
**Connected systems:** ATS, approved sourcing tools, email, calendar  
**Starter prompt pattern:** Find candidates meeting must-have criteria, exclude anyone already in ATS, explain evidence for each match, draft personalized outreach. Do not contact anyone.  
**Progression:** Add approval gates before any external outreach; respect candidate privacy, regional requirements, and platform terms.

### 8.3 Paid Media

**Ownership:** Campaign monitoring and budget recommendations  
**Connected systems:** Advertising platforms, analytics, budget spreadsheets, Slack  
**Starter prompt pattern:** Pull current spend/performance by campaign, compare against monthly budget and target CAC, recommend reallocations with supporting numbers, draft Slack update. Do not change budgets or send the message.  
**Progression:** Campaign changes should remain behind approval even after analysis becomes routine.

### 8.4 Expense Manager

**Ownership:** Weekly expense reconciliation and missing-information follow-up  
**Connected systems:** Expense system, email, shared drive, finance spreadsheets  
**Starter prompt pattern:** Build weekly expense summary, match receipts from finance inbox, flag missing categories or policy exceptions, draft follow-ups per owner. Do not send messages or change reimbursements.  
**Progression:** Require policy citations on every exception and totals that reconcile to source data.

### 8.5 Product Performance

**Ownership:** Targeted performance investigations with evidence  
**Connected systems:** Observability tools, analytics, incident tooling, source-control links  
**Starter prompt pattern:** Investigate latency increases by reviewing dashboards, traces, and flamegraphs. Identify highest-confidence hotspot, return write-up with screenshots and direct links. Separate facts from hypotheses. Do not change alerts or production settings.  
**Progression:** Routines are appropriate for recurring health reports but not for unsupervised production changes.

### 8.6 Bug Reproduction

**Ownership:** Turning reports into reliable reproduction packs  
**Connected systems:** Issue tracker, staging environment, browser, network tools  
**Starter prompt pattern:** Read bug report and reproduce in staging with fresh test account. Return exact steps, expected and actual behavior, screenshots, browser/OS details, console/network notes, and minimal test case. Do not use production customer data.  
**Progression:** Test credentials should be provided via secure handoff, not through chat.

### 8.7 Account Health

**Ownership:** Risk and expansion signals across a customer portfolio  
**Connected systems:** CRM, product usage, support, billing, customer-success notes  
**Starter prompt pattern:** Review portfolio accounts combining recent usage, support escalations, renewal timing, and stakeholder activity into a ranked watch list. Each entry needs evidence, significance, and suggested next step. Do not contact customers or edit the CRM.  
**Progression:** Risk thresholds should be defined in the bot description to keep weekly results consistent.

### 8.8 Chief of Staff

**Ownership:** A source-linked digest of what changed and what needs attention  
**Connected systems:** Slack, email, calendar, meeting notes, planning documents  
**Starter prompt pattern:** Review activity since yesterday across approved channels, inbox, calendar, and meeting notes. Return only items mapping to documented priorities. Each item needs the source, why it matters, proposed next step, and whether a decision is owed. Do not send messages or change meetings.  
**Progression:** Tune by marking useful vs. noise items, then schedule the digest at a reviewable time.

### 8.9 Universal Bot-Building Framework

The documentation provides a seven-step framework applicable to any role:

1. Place the job definition, source systems, output format, and standing boundaries into the bot description
2. Execute one real task at a safe scope
3. Correct output until it reaches reviewable quality
4. Save the successful process as a skill
5. Test on a second input
6. Create a routine only when retries and failure cases are defined
7. Keep consequential external actions behind approval

---

## 9. Security Model & Governance

### 9.1 Approvals System

The approvals system keeps consequential actions under the member's control. The strongest boundary is having members explicitly state what a Bot may change and where it must stop in the request itself.

When approval is needed, the conversation shows the proposed operation and its inputs. Three options are available:

| Option | Effect |
|--------|--------|
| **Allow once** | Bot proceeds with that single action |
| **Always allow** | Saves a matching rule for future use |
| **Deny** | Blocks the action |

An approval controls the proposed action, not work already completed. Users should never approve an action whose target or effect they cannot identify.

**Approval expiration:** From an active chat, the approval waits indefinitely. From background work (routines, triggers, messages from other Bots), approval requests expire after about 10 minutes; the card then shows "Expired" and the action does not run.

### 9.2 Auto Review

Auto Review is an independent review model evaluating risky Bot actions before execution. It covers:
- Shell commands
- Plugin calls
- Computer use
- Automation writes (changes to routines and event triggers)
- Delegation (Cloud Agent and subagent launches)

Three possible outcomes: proceed, require approval, or deny.

**Two rule types:**

| Rule Type | Behavior |
|-----------|----------|
| **Ask first** | Always stops matching actions for user review |
| **Allow automatically** | Lets matching actions proceed unless the automated review finds another reason to stop |

If both rule types match, Ask first wins.

**Limitations:** Auto Review does not review every side effect. Memory writes and most settings changes are examples. It should be treated as a complement to explicit boundaries and least privilege, alongside controls not dependent on model judgment.

### 9.3 Identity and Sign-ins

Members sign in via their Cursor account, with existing SSO configuration applying. SAML 2.0 SSO is supported with Okta, Microsoft Entra, Google Workspace, and OneLogin. SSO can be required for all members, blocking password login. SCIM 2.0 provisioning and deprovisioning is Enterprise only.

A critical aspect of the identity model: a Bot has no identity or credentials of its own. Bots act as the signed-in member — they never hold more access than that person, and every action is attributable to a named member. Connector tokens stay on Cursor's backend — Bots invoke tools without receiving OAuth tokens, and tokens are never stored on the computer.

### 9.4 Network Policy (Enterprise Only)

Network policy controls which destinations team computers can reach, with four modes:

| Mode | Effect |
|------|--------|
| **No Policy (Allow All)** | Default for teams without a policy |
| **Allow All Network Access** | Explicitly permits all destinations |
| **Defaults + Team Allowlist** | Cursor's default destinations plus custom entries |
| **Team Allowlist Only** | Custom list only, plus minimal destinations needed for computer function |

Destinations include web domains and IP ranges with ports, with no cap on entry count. Directory groups (Enterprise only) can override the team-wide network policy. The connector policy and network policy are separate layers — closing both requires both controls.

### 9.5 Static Egress IPs

Hosted computers use shared static egress IP addresses by default. Ranges are shared across all Grok Bot customers — dedicated per-customer IPs are unavailable. Members can route traffic through their desktop to use its network/IP. Enterprise teams can install their own networking client on every team computer via Team Setup.

### 9.6 Prompt Injection Defenses

External content (web pages, plugin results, command output) can attempt to steer a Bot. Defenses are layered:
- Auto Review checks Bot actions against the member's request (when enforcement is on)
- Controls independent of model judgment: network policy, per-action approvals, per-user isolation
- Outside content is marked as untrusted data when presented to the model

These controls reduce but do not eliminate risk from malicious content.

### 9.7 Data Retention and Deletion

Each member's computer keeps local files, browser sessions, and browser-saved data on a durable disk across sessions. Connector tokens are never stored on the computer.

Key lifecycle events:
- **Idle computers hibernate automatically** — hibernation is not deletion
- **Image updates preserve files** — computers on a stale image are recreated with member files preserved
- **Member resets keep synced data** — recent unsynced work can be lost
- **Deletion follows the DPA** — data deleted or returned within 30 days of written direction after service ends
- **Backups run daily** — production control plane covered by daily encrypted backups, replicated to a separate recovery facility

Not available: per-organization retention policy, customer-managed point-in-time restore of an individual computer.

### 9.8 Data Residency

Grok Bot computers run in the United States. This is not the same as Cursor's "US-only data residency" program, which does not apply to Grok Bot by default. Written residency commitments are available through the account team.

### 9.9 Models and Data Privacy

Cursor manages model selection — there is no customer-facing model picker. The serving mix can change over time with no fixed vendor set guaranteed. Usage analytics show the model per request, including failovers.

Model allowlist (Enterprise only): enforcement is not guaranteed — onboarding presents an acknowledgment that Grok Bot may not follow it.

With Privacy Mode enabled, customer data is not used for training. Model providers do not keep prompts or outputs (zero data retention). Providers may run abuse and safety classifiers; flagged data may be stored for investigation.

### 9.10 Certifications

Anysphere (the company behind Cursor) holds ISO/IEC 27001 and ISO/IEC 42001, issued by Schellman. Grok Bot is included in the current ISO scope:
- **ISO 27001**: Information security management system
- **ISO 42001**: AI management system (governance of AI built and operated by Cursor)

Certificates and reports are available at trust.cursor.com.

### 9.11 Local Execution Controls

Bots can act on a member's own machine via the desktop app. This is separate from hosted computer work and distinct from Auto Review.

Per-command approval is the default. Options under Settings → General → Bot → Execution on Local Computer:

| Setting | Behavior |
|---------|----------|
| **Ask every time** | Default — prompt for each command |
| **Always allow** | No prompts |
| **Never allow** | Block all local execution |

The recommendation is "Never allow" unless a Bot has a specific reason to work on local files. Enterprise admins can cap the policy team-wide.

---

## 10. Enterprise & Teams Features

### 10.1 Plan Availability

| Plan | Access |
|------|--------|
| **Individuals** | Included with every paid Cursor plan or via individual SuperGrok link |
| **Teams** | Included; every member has access; usage follows seat allowance |
| **Enterprise** | Admin enables from dashboard |

### 10.2 Enabling Grok Bot

**Teams Plan:** Enabled by default — no admin action needed. Stays off for teams on Privacy Mode (Legacy) or legacy request-based plans. No switch exists to turn it off on Teams.

**Enterprise Plan:** Admin enables from the Cursor dashboard. Access can be given to all members or limited to specific groups via "Manage Group Access." Turning off blocks every member without deleting their computers.

### 10.3 Pre-Rollout Checklist

1. Move off Privacy Mode (Legacy) — it blocks Grok Bot entirely
2. Plan for shared static egress IPs if the company restricts by source IP
3. Allow Cursor domains including nested `*.*.cursorvm.com` pattern on TLS-inspecting proxies; exempt from inspection
4. Determine how members sign into company tools from the computer
5. Review inherited policies — Team Rules, connector policy (all plans), Auto-review rules, and MCP allowlist (Enterprise)

### 10.4 Admin Controls (Complete Reference)

#### Access and Identity
- **Enable Grok Bot** (Enterprise only): Organization-wide switch with group-level access management
- **SCIM** (Enterprise only): SCIM 2.0 provisioning/deprovisioning through identity provider (supports Okta and Entra ID)

#### Agent Capabilities
- **Cloud Agents** (Teams & Enterprise): Allows/blocks Bots delegating coding tasks to Cloud Agents. On by default.
- **Public Template Sharing** (Teams & Enterprise): Controls whether members can publish Bot templates outside the team. Enterprise teams start with sharing off.
- **Connector Policy** (Teams & Enterprise): Grok Bot inherits the team's Cursor connector policy — no separate Grok Bot connector list. MCP allowlist is Enterprise only.
- **Execution on Local Computer** (Teams & Enterprise): Caps what Bots do on the member's own machine. Three options: Always allow (default), Ask every time, Never allow.
- **Allow Local Egress** (Enterprise only): Lets members route Grok Bot web traffic through their own computer. On by default.

#### Rules and Approvals
- **Team Rules** (Teams & Enterprise): Rules every member's Bot follows. Rules applied to Grok Bot are always required — members cannot turn them off.
- **Enforce Auto-review** (Enterprise only): Prevents members from turning Auto-review off. Off by default.
- **Auto-review Rules** (Enterprise only): Team-wide Ask first and Allow automatically rules. Apply on top of members' own rules. Ask first wins when rules conflict.

#### Computers and Network
- **Network Controls** (Enterprise only): Restricts destinations team computers can reach with four modes.
- **Team Setup** (Enterprise only): Manifests of install scripts running on every team computer. Ensures same tooling everywhere.
- **Team Secrets** (Enterprise only): Team-wide values read as environment variables by Team Setup scripts. Stored encrypted; dashboard never shows value after save.

**Team Secrets specifications:**
- Up to 100 secrets per team
- Up to 32 KB per value
- Up to 96 KB total
- Names must be valid environment variable names
- Reserved names rejected: `PATH`, `HOME`, anything starting with `SAND_` or `LD_`
- Not available through Admin API
- Multi-team members get no secrets from any team (security constraint)

#### Computer Management
- **Manage Bot Computers** (Enterprise only): Requires organization admin rights.
  - **Recreate**: Moves to latest image and Team Setup; keeps Bots, files, logins
  - **Terminate**: Ends current work, keeps durable disk; next session starts fresh
  - **Terminate Inactive Computers**: Terminates after 30 days without use; off by default
- None of these remove access — access removal requires removing the member from the team or turning off Grok Bot for their group, plus revoking IdP sessions.

### 10.5 Logging and Audit

#### Audit Logs (Enterprise Only)
Cover admin, security, authentication events plus Grok Bot control-plane events including Bot creation, member access changes, Team Setup manifests, MCP authentication, Slack account links, and routines. Filterable by application; streamable to a SIEM.

#### Action Recording (Enterprise Only)
Records every tool call and outcome, Auto-review decisions, MCP tool calls, shell commands, browser navigations, computer use sessions, file transfers, messages, routine runs, guardrail interventions, skills read, and subagent/cloud agent handoffs. Events are metadata, sanitized before storage/export. Off by default. 90-day retention.

**Sanitization details:**
- Shell commands: secret-scrubbed
- Browser navigations: `scheme://host/path` with title, strips query strings and credentials
- Computer use sessions: action/screenshot counts and duration only — no screenshots, clicks, or typed text
- Tool arguments/results, file paths/names, message bodies never exported

#### Conversation Content Export (Enterprise Only, Opt-in)
Streams text of user prompts, assistant responses, and MCP tool arguments/results via OpenTelemetry Export. Scrubs known credential shapes, PEM blocks, and email addresses into `[REDACTED: ...]` markers. Pattern matching cannot catch everything — the team owns residual risk.

#### OpenTelemetry Export (Enterprise Only)
Streams usage metrics and logs to the customer's collector. Records may include member email (`cursor.user.email`).

### 10.6 Group Settings (Enterprise Only)

Groups only widen the team baseline — a group can grant its members more than the team allows, never less. A member in multiple groups gets the most permissive result.

Four sections in a group's Grok Bot tab:
1. **Agent Capabilities**: Cloud Agents, local execution ceiling, local egress, Auto-review enforcement override, group Auto-review rules
2. **Network**: Group's own network policy; locked team policy overrides
3. **Group Rules**: Combined with Team Rules; members cannot turn off
4. **Setup Scripts**: Manifests running alongside Team Setup; same structure, same Team Secrets

### 10.7 Admin API

Manages: enable/disable Grok Bot, capabilities, Enforce Auto-review, group access, network policy, team rules, and setup scripts. Team Secrets are dashboard only — not available through the Admin API.

### 10.8 Enterprise-Only Features Summary

| Feature |
|---------|
| Enable/disable Grok Bot org-wide switch |
| SCIM provisioning |
| Allow Local Egress control |
| Enforce Auto-review |
| Auto-review rules |
| Network Controls |
| Team Setup |
| Team Secrets |
| Manage Bot Computers |
| Action Recording |
| Conversation content export |
| Audit logs |
| OpenTelemetry Export |
| Group settings (all sections) |
| MCP allowlist |
| Computer termination by admin |
| Capping local execution policy team-wide |

---

## 11. Pricing & Plans

### 11.1 Cursor Plan Tiers (Individual)

| Plan | Grok Bot Access | Usage Level |
|------|----------------|-------------|
| **Cursor Pro** | Included | Weekly usage, below Pro+ |
| **Cursor Pro+** | Included | Generous weekly usage, below Ultra |
| **Cursor Ultra** | Included | Highest weekly usage |

### 11.2 Cursor Team Plans

| Plan | Access | Details |
|------|--------|---------|
| **Cursor Teams** | Every member gets Grok Bot | Usage draws from Teams plan's allowance per seat; on-demand enabled by default |
| **Cursor Enterprise** | Admin-managed | Does not accept personal SuperGrok links; stays on Cursor contract |

### 11.3 SuperGrok Tiers (Linked Usage via xAI/X)

| Tier | Usage Level | Billing |
|------|-------------|---------|
| **SuperGrok** | Linked usage, below Plus | xAI |
| **SuperGrok Plus** | Generous linked usage, below Heavy | xAI |
| **SuperGrok Heavy** | Highest linked usage | xAI |
| **SuperGrok Lite** | **Not included** — upgrade required | N/A |
| **X Premium+** | Linked usage, below SuperGrok Plus | X |
| **Grok Business** | Matches license on seat (SuperGrok or SuperGrok Heavy) | xAI |
| **Grok Enterprise** | Managed by account manager | xAI |

### 11.4 Usage Model

**Weekly Usage (Included):** Resets weekly. Amount depends on tier. Included weekly usage is not a monthly limit.

**On-Demand Usage:** Kicks in when weekly usage is exhausted. Billed through Cursor. Counts toward the on-demand monthly limit. A limit is not a hard stop in the middle of a run — a running bot can finish past the cap. After exceeding the limit, on-demand stops until the limit is raised or the billing cycle resets.

### 11.5 Usage Hierarchy (Highest to Lowest)

1. Cursor Ultra / SuperGrok Heavy — highest
2. Cursor Pro+ / SuperGrok Plus — generous, below top
3. Cursor Pro / SuperGrok — standard
4. X Premium+ — below SuperGrok Plus
5. SuperGrok Lite — no access

### 11.6 Key Billing Rules

- **No stacking**: A Cursor plan and a SuperGrok or X Premium+ link do not stack — they do not add extra Grok Bot usage on top of each other
- **Linking is permanent**: A SuperGrok or X Premium+ link cannot be unlinked or moved to a different Cursor account
- **Cross-platform**: macOS and iOS share a single usage bucket
- **Upgrading**: Grant follows the new tier; allow up to 24 hours for refresh
- **Downgrading**: Lowers the grant after up to 24 hours; usage already consumed that week still counts

### 11.7 Free Trial

Usage credit-based (not time-based, though a 7-day window applies). Metered by agent steps and tokens rather than number of messages. The trial never becomes a paid plan. Cancel Trial removes remaining credit permanently. iOS App Store intro offers are separate — managed through Apple.

### 11.8 Refunds

No separate Grok Bot subscription means no separate refund path. Not refundable: on-demand usage already consumed; mid-cycle downgrades with usage. iOS/Android charges refunded only through Apple or Google respectively. SuperGrok/X Premium+ refunds handled by xAI or X, not Cursor.

---

## 12. Platform Support & Mobile

### 12.1 Desktop Support

| Platform | Architectures |
|----------|---------------|
| macOS | Apple silicon and Intel |
| Windows | x64 and Arm64 |
| Linux | x64 and Arm64 (.deb, .rpm, AppImage) |

### 12.2 Mobile Support

| Platform | Requirements |
|----------|-------------|
| iPhone | iOS 18 or later |
| iPad | iPadOS 18 or later (via iOS app) |
| Android | Android 9 or later |

Available on the App Store and Google Play.

### 12.3 Mobile Capabilities

The mobile app shares the same Bots, conversations, routines, connectors, and cloud computer as the desktop app. Work continues in the cloud when the app is closed.

Full mobile messaging capabilities:
- Send text, dictate, start voice chat, play voice memos
- Take or attach photos, choose images/files from device
- Mention Bots, use `@everyone` in groups
- Reply in threads, react to messages
- View and take over the shared cloud computer
- View routine schedules, toggle active/pause, delete routines

**iPhone share sheet**: Send photos, files, links, or text from other apps into a chat.  
**Android share sheet**: Currently accepts text only.

### 12.4 Mobile Limitations

- Some advanced desktop controls and teach-by-demonstration workflows are not available
- Routine schedule/instruction editing and testing require the desktop app
- Android share sheet only accepts text
- Language options are fewer than on desktop

---

## 13. X (Twitter) Integration

### 13.1 Tag @bot on X

Users can tag @bot in any X post or reply, and the user's main Bot picks up the post as a task. On X, @bot only posts a brief confirmation reply — all work and results stay within the Grok Bot app's conversation.

### 13.2 Context Passed to the Bot

The Bot receives:
- The user's post (the one tagging @bot)
- The post replied to (if applicable)
- Any post that either of those two quotes
- Still photos included in any of the above

Videos and GIFs are not supported.

### 13.3 Setup Requirements (All Four Needed)

1. Grok account with X connected (Settings → Account → Connect beside 𝕏 Account on grok.com)
2. Grok Bot access on that same Grok account
3. At least one self-created Bot (shared Bots cannot take tagged requests)
4. X account based in an eligible region

### 13.4 Regional Availability

**Not available in:** Australia, United Kingdom, European Union member states, Iceland, Liechtenstein, Norway.

Region is determined by the country on record for the X account. Physical location and VPN usage have no effect.

### 13.5 @bot Reply Meanings

| Reply | Meaning |
|-------|---------|
| Short confirmation line | Main Bot received the task — open Grok Bot app to follow progress |
| "Sign up for Grok Bot" | No Grok account connected to that X account |
| "Grok Bot isn't set up yet" | Accounts connected but no self-created Bot exists |

### 13.6 When @bot Stays Silent (No Reply)

Six documented causes:
1. Region restriction
2. Missing direct tag (replied in thread but didn't tag @bot in specific reply)
3. Conflict with @grok (post also tags @grok)
4. Unsupported media (video or GIF in post, parent, or quoted post)
5. Moderation block
6. Account/usage issues (not linked or weekly usage exhausted)

---

## 14. Limitations & Considerations

### 14.1 Architectural Limitations

- **No on-premises deployment**: Grok Bot runs only on Cursor-hosted cloud computers. Not supported: on-premises deployment, deployment inside customer perimeter, or bring-your-own-image.
- **Shared computer is not a security boundary**: All Bots for one user share a single computer. Bots isolate personalities and workspaces, not compute.
- **No customer-facing model picker**: Cursor manages model selection. The serving mix can change over time.
- **No dedicated egress IPs**: Static egress IP ranges are shared across all Grok Bot customers.
- **US data residency only**: Grok Bot computers run in the United States.

### 14.2 Operational Limitations

- **Single computer-use task per Bot screen**: A Bot can only run one computer-use task on its screen at a time.
- **Website blocking**: Sites may block automation, expire sessions, or require human steps.
- **Auto Review coverage**: Does not review every side effect — memory writes and most settings changes are excluded.
- **Model allowlist not guaranteed**: Enterprise model allowlist enforcement is configuration-dependent and may not be followed.
- **No DLP hooks**: Dedicated DLP hooks are unavailable. Restricting egress limits where data can be sent, but comprehensive data loss prevention is not built in.

### 14.3 Usage Limitations

- **Weekly usage caps**: Usage resets weekly; amount depends on tier.
- **No stacking**: Multiple subscriptions do not combine usage grants.
- **Linking is permanent**: SuperGrok/X Premium+ links cannot be unlinked.
- **File size limits**: Documents/images/audio max 25 MB; video max 200 MB.
- **6 attachments per message**: Desktop composer limit.
- **50 routines per Bot**: Maximum routine count.
- **5-minute minimum routine interval**: Minimum scheduling frequency.
- **10-minute approval expiration**: Background work approval requests expire.

### 14.4 Regional Limitations

- @bot on X not available in EU, UK, Australia, Iceland, Liechtenstein, Norway.
- Language options are fewer on mobile than desktop.

### 14.5 Mobile Limitations

- Teach-by-demonstration not available on mobile.
- Routine editing/testing requires desktop.
- Android share sheet text-only.

---

## 15. Comparative Analysis

### 15.1 Positioning in the AI Agent Landscape

Grok Bot occupies a distinct position in the AI agent landscape. Rather than being a developer-focused coding assistant (like GitHub Copilot or Cursor's own code completion), it is a general-purpose business automation agent. Rather than being a chatbot with ephemeral context (like standard ChatGPT or Grok chat), it maintains persistent state across sessions.

### 15.2 Key Differentiators vs. Conventional AI Assistants

| Dimension | Conventional AI Chat | Grok Bot |
|-----------|---------------------|----------|
| **Context** | Ephemeral, resets per session | Persistent memory, files, browser sessions across sessions |
| **Execution** | Generates text/code output only | Operates real applications via cloud computer |
| **Identity** | Single anonymous agent | Named Bots with specialized roles |
| **Coordination** | Single agent | Multi-bot teams with group chats and handoffs |
| **Background work** | Requires user's device open | Runs in cloud; laptop can be closed |
| **Automation** | Manual trigger each time | Skills and routines with scheduling and event triggers |
| **Approval model** | None (or binary allow/block) | Granular per-action approvals with Auto Review |
| **Enterprise governance** | Limited | Network policy, SCIM, audit logs, action recording, team rules |

### 15.3 Strengths

1. **True computer use**: Bots operate real applications, not simulated environments.
2. **Persistent cloud computer**: State survives across sessions and device closures.
3. **Multi-bot coordination**: Enables organizational patterns with specialist roles.
4. **Enterprise-grade security**: ISO certifications, network policies, SCIM, audit logs.
5. **Progressive trust model**: Start read-only, add approvals gradually, automate only proven workflows.
6. **Cross-platform**: Desktop (Mac/Win/Linux) + Mobile (iOS/Android) with full sync.

### 15.4 Considerations

1. **Cloud-only execution**: No on-premises deployment option limits adoption for highly regulated industries.
2. **Shared egress IPs**: Cannot identify a specific organization's traffic.
3. **Model opacity**: No customer-facing model picker; serving mix can change.
4. **Cursor dependency**: Tightly coupled to Cursor's ecosystem and billing.
5. **Regional restrictions**: @bot on X unavailable in EU/UK/AU.

---

## 16. Conclusion

### 16.1 Summary

Grok Bot represents a significant evolution in the AI agent paradigm — moving from stateless, text-only assistants to persistent, computer-operating teammates. The platform's architecture — centered on per-user Firecracker microVMs, a shared computer model, and a layered security stack — provides a foundation for delegating real business work to AI agents while maintaining human oversight through explicit approval boundaries and Auto Review.

The pricing model, integrated through Cursor and SuperGrok subscriptions, offers tiered access from individual practitioners to enterprise deployments. The eight documented use cases (sales outbound, talent scouting, paid media, expense management, product performance, bug reproduction, account health, and chief of staff) demonstrate the breadth of applicable domains, all following the same progressive pattern: read-only first, then drafts, then approved actions, then automated routines.

### 16.2 Key Takeaways

1. **Grok Bot is not a chatbot** — it is a persistent AI teammate that operates a cloud computer with real applications.
2. **The shared computer model enables handoffs** between specialized Bots without re-authentication.
3. **Security is layered** — per-user isolation, no default access, human approval gates, Auto Review, network policy, and audit logging.
4. **Enterprise adoption requires planning** — network policies, identity decisions, and approval rules should be configured before rollout.
5. **Progressive trust is the recommended adoption pattern** — start with safe, read-only tasks and gradually expand scope as confidence grows.
6. **Automation should follow reliability** — skills and routines should only be created after manual processes are proven and failure cases are defined.

### 16.3 Future Implications

Grok Bot's introduction of named, persistent AI agents with real computer access and inter-agent coordination represents a shift toward AI as organizational infrastructure rather than individual productivity tools. The enterprise governance features — audit logging, action recording, network controls, and SCIM provisioning — suggest that xAI and Cursor are positioning the platform for adoption at the organizational level, where accountability, compliance, and administrative control are prerequisites.

The platform's emphasis on human-in-the-loop approval for all consequential actions, combined with the progressive trust model, addresses the primary concern in enterprise AI adoption: maintaining control while enabling automation. As the AI agent landscape continues to evolve, Grok Bot's architecture provides a reference implementation for how persistent, tool-using AI agents can be integrated into business operations with appropriate governance guardrails.

---

## References

1. xAI. "Grok Bot Overview." https://docs.x.ai/grok-bot/overview
2. xAI. "Get Started with Grok Bot." https://docs.x.ai/grok-bot/get-started
3. xAI. "Grok Bot Use Cases." https://docs.x.ai/grok-bot/use-cases
4. xAI. "The Computer and Apps." https://docs.x.ai/grok-bot/computer-and-apps
5. xAI. "Create and Manage Bots." https://docs.x.ai/grok-bot/bots
6. xAI. "Grok Bot Security." https://docs.x.ai/grok-bot/security
7. xAI. "Skills, Routines, and Automations." https://docs.x.ai/grok-bot/skills-routines-and-automations
8. xAI. "Teams and Enterprises." https://docs.x.ai/grok-bot/teams-and-enterprises
9. xAI. "Tag @bot on X." https://docs.x.ai/grok-bot/tag-on-x
10. xAI. "Grok Bot Mobile." https://docs.x.ai/grok-bot/mobile
11. xAI. "Files and Results." https://docs.x.ai/grok-bot/files-and-results
12. xAI. "Chat and Collaboration." https://docs.x.ai/grok-bot/chat-and-collaboration
13. Cursor. "Grok Bot Plans and Billing." https://cursor.com/help/grok-bot/plans
14. xAI. "Approvals, Security, and Privacy." https://docs.x.ai/grok-bot/approvals-security-and-privacy
15. Anysphere. "Trust Center." https://trust.cursor.com

---

*This paper is based entirely on official documentation published by xAI and Cursor as of October 2026. All claims, specifications, and features described herein are sourced directly from the referenced documentation. No information has been assumed or extrapolated beyond what is explicitly stated in the source material.*
