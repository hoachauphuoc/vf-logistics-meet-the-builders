# LinkedIn copy

Ready-to-paste text for the Meet the Builders badge post and the LinkedIn
Projects section. It has no links on purpose. Attach
`docs/meet-the-builders-badge.webp` as the post image.

## Post

> Copy everything between the lines. After pasting, retype the two @ mentions
> and pick the pages from LinkedIn's dropdown, or they will not link.

---

I'm now a featured builder in Google Gen AI APAC 2026, and my project is live on the Meet the Builders map. 🎉

The problem: Vietnamese logistics operators lose money to shipment fraud that threshold rules cannot see. Freight 60% below the route average looks like a promo. A shipper with two lifetime transactions looks like a new customer. Catching it means reading many weak signals together.

VF Logistics is an autonomous compliance pipeline. Four Gemini agents read bills of lading, then screen for fraud, screen for sanctions and investigate. A case goes from upload to decision without anyone stepping it through.

The part I care about most is that the agents are not trusted:
🔒 A deterministic risk floor, computed with no model involved. A model can raise a score but never lower it. One dual-use shipment was scored 15 by the model and has an effective risk of 85, so it waits for a person.
🛡️ Model Armor screens documents for prompt injection before Gemini ever reads them.
📜 Autonomy is granted, not assumed. A human publishes a versioned Delegation Boundary. Without one, the system refuses every action.

What I learned: every control passed review on its own. The bugs lived in how they combined.

Built on Gemini 3.5 Flash and Flash-Lite on Vertex AI, with Cloud Run, Firestore, Pub/Sub, Cloud Storage and Model Armor.

Thanks @Hack2skill and @Google Cloud for the programme.

#MeetTheBuilders #1000Builders1000Stories #GenAI #GoogleCloud #Gemini #AIAgents

---

## Projects section (profile → Add section → Projects)

**Project name:** VF Logistics — Governed Autonomous Fraud Detection

**Associated with:** Google Gen AI Academy APAC 2026 (Meet the Builders)

**Description:**

An autonomous compliance pipeline for shipping documents. Four Gemini agents handle document intake, fraud detection, sanctions screening and investigation. A bill of lading or shipment event goes to a decision with no human stepping it through, and a person sees only the cases that fall outside a policy a person published. The agents are treated as claims, not findings. A deterministic verifier sets a risk floor that no model can argue down. Model Armor blocks prompt injection before a document reaches Gemini. A versioned Delegation Boundary, published by a human, defines what the system may do; without one it fails closed. The system is built on Gemini 3.5 Flash and Flash-Lite through Vertex AI, with Cloud Run, Firestore, Pub/Sub and Cloud Storage. It scales to zero when idle.

**Skills:** Gemini · Vertex AI · Google Cloud Run · Firestore · Multi-agent Systems · AI Security · Python

**Media:** attach `docs/meet-the-builders-badge.webp`. You can also add screenshots from `docs/screenshots/`.

## Checklist

- [ ] Attach the badge image to the post
- [ ] Re-select @Hack2skill and @Google Cloud from the mention dropdown
- [ ] Publish the post
- [ ] Add the Projects entry to your profile
- [ ] Paste the post link into the Hack2skill Google Form from the badge email
