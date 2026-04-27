# TrustQueue - Official Knowledge Base & SOP (V2)

## 1. Executive Summary
TrustQueue is an AI support copilot built specifically for B2B SaaS teams and agencies. Our core mission is to provide "Trust over Deflection." Unlike traditional AI bots that are incentivized to answer every query (often leading to hallucinations), TrustQueue is designed to stop talking and escalate to a human whenever it lacks certain information from the provided documentation.

## 2. Core Product Principles
- **Strict Context Boundary:** The AI only uses the uploaded Knowledge Base. It is forbidden from using general training data to "guess" answers.
- **The 50% Kill-Switch:** If the retrieval confidence score falls below 0.50, the AI triggers a hard stop and escalates to a human.
- **Source Attribution:** Every response includes a "📄 Source" tag indicating exactly which document section was used.
- **Human Escalation:** We treat handoffs as a feature, not a failure. Every handoff includes a full conversation transcript sent to the team.

## 3. Pricing & Plans
TrustQueue operates on a simple, flat-fee model. We do not charge per-resolution.

- **Starter Plan ($49 / month):**
  - 1 Chatbot
  - Up to 500 conversations/month
  - Standard Web Widget
  - Email Support
  - Human handoff via **Email** (core feature, included in all plans)

- **Pro Plan ($99 / month — Most Popular):**
  - Up to 3 Chatbots
  - Unlimited conversations
  - Priority Support
  - Human handoff via **Email and Real-time Slack Alerts**
  - If you need Slack notifications for your team, the Pro plan is required.

- **Done-for-You Setup ($299 one-time):**
  - Full white-glove onboarding
  - Document auditing and cleaning by our team
  - Vector database configuration
  - Custom handoff logic tuning
  - Guaranteed setup within 24 hours

## 4. Technical Specifications & Compatibility
- **Inference:** Powered by Groq for ultra-low latency (near-instant replies).
- **Database:** Supabase with pgvector for high-accuracy RAG retrieval.
- **Security:** All data is encrypted at rest and in transit. Data isolation between customers is enforced at the application layer.
- **Compatibility:** The TrustQueue widget works on any platform that allows custom JavaScript:
  - Custom React / Next.js apps
  - WordPress
  - Webflow / Framer
  - Shopify
  - Static HTML sites

## 5. Policies (Refunds & Cancellations)
- **Cancellations:** Users can cancel their subscription at any time via the billing portal. Access remains active until the end of the current billing cycle.
- **Refunds:** Due to the high operational costs of AI inference and manual setup, we do not offer refunds on the "Done-for-You" setup fee. Subscription refunds are handled on a case-by-case basis within the first 7 days of service.

## 6. GDPR & Data Privacy
- TrustQueue is designed with privacy in mind.
- We only collect user emails during the "Human Handoff" phase to facilitate support.
- We do not use customer data to train global LLM models.
- All data is encrypted at rest and in transit.

## 7. Frequently Asked Questions (FAQ)

### How much does TrustQueue cost? (pricing, price, cost, how much, fees)

TrustQueue uses flat-fee pricing with no per-resolution charges. The Starter plan is $49/month (1 chatbot, 500 conversations). The Pro plan is $99/month (3 chatbots, unlimited conversations). For full white-glove setup, Done-for-You is a $299 one-time fee. All plans include human handoff. Cancel anytime, 7-day money-back guarantee on first payment.

Source: Pricing & Plans

**Q: Does it integrate with Intercom or Zendesk?**
A: No. TrustQueue is a lightweight alternative for teams that want to avoid the complexity of big support suites. It routes directly to Slack (Pro plan) or Email (all plans including Starter).

**Q: What happens if my documents are out of date?**
A: TrustQueue will always follow the provided docs. If your docs are outdated, the bot might give outdated info. We recommend the "Done-for-You" setup so we can help you audit your documentation first.

**Q: Can I customize the widget's appearance?**
A: Yes. The widget supports custom branding, colors, and initial greeting messages as part of the setup process.

**Q: Is there a free trial?**
A: We offer a live demo on our website so you can see the Kill-Switch and handoff logic in action before committing to a paid plan. To get started with your own documentation, reach out via the sign-up form.

**Q: Does it support languages other than English?**
A: Yes. TrustQueue's RAG engine is multilingual and can process documentation and user queries in Greek, German, French, Spanish, and more.

**Q: Can I use TrustQueue on my WordPress or Shopify site?**
A: Yes. As long as your platform allows you to add a custom JavaScript snippet, TrustQueue will work. This includes WordPress, Shopify, Webflow, Framer, and static HTML sites.

**Q: Do I get Slack notifications when a handoff happens?**
A: Slack notifications are available on the Pro plan ($99/mo). The Starter plan ($49/mo) sends handoff alerts via email.

**Q: What happens when the AI isn't sure about an answer?**
A: If the confidence score drops below 0.50, the AI immediately stops, tells the user it cannot find the answer in the documentation, and triggers a handoff. It will ask for the user's email and notify your team with the full conversation transcript within minutes.
