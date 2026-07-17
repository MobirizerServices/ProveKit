# Demo flow gallery

286 ready-to-import example flows. Each references the keyless **Demo Assistant (mock)** connection, so they run offline out of the box. Import via the app (Flows → import) or `POST /api/import`, then hit Run.

| Flow | What it does |
|---|---|
| `content-moderation-faq-match-answer.yaml` | Match a text to a topic, then answer in that context. |
| `content-moderation-answer.yaml` | Read a text, draft a helpful reply. |
| `content-moderation-classify-intent.yaml` | Classify a text into one label. |
| `content-moderation-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `content-moderation-extract-to-json.yaml` | Extract structured fields from a text as JSON. |
| `content-moderation-language-route.yaml` | Detect the language of a text; answer directly if English, else translate first. |
| `content-moderation-moderation-gate.yaml` | Check a text for policy issues before publishing. |
| `content-moderation-score-gate.yaml` | Score a text 1-5 for priority, then gate on the number. |
| `content-moderation-sentiment-route.yaml` | Detect sentiment of a text, escalate the negative ones. |
| `content-moderation-summarize-then-decide.yaml` | Summarize a text, then branch on whether it needs follow-up. |
| `content-moderation-tag-enrich.yaml` | Produce a JSON list of topic tags for a text. |
| `content-moderation-translate-reply.yaml` | Translate a text to English, then draft a reply. |
| `content-moderation-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `customer-support-faq-match-answer.yaml` | Match a message to a topic, then answer in that context. |
| `customer-support-answer.yaml` | Read a message, draft a helpful reply. |
| `customer-support-classify-intent.yaml` | Classify a message into one label. |
| `customer-support-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `customer-support-extract-to-json.yaml` | Extract structured fields from a message as JSON. |
| `customer-support-language-route.yaml` | Detect the language of a message; answer directly if English, else translate first. |
| `customer-support-moderation-gate.yaml` | Check a message for policy issues before publishing. |
| `customer-support-score-gate.yaml` | Score a message 1-5 for priority, then gate on the number. |
| `customer-support-sentiment-route.yaml` | Detect sentiment of a message, escalate the negative ones. |
| `customer-support-summarize-then-decide.yaml` | Summarize a message, then branch on whether it needs follow-up. |
| `customer-support-tag-enrich.yaml` | Produce a JSON list of topic tags for a message. |
| `customer-support-translate-reply.yaml` | Translate a message to English, then draft a reply. |
| `customer-support-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `developer-tooling-faq-match-answer.yaml` | Match a issue to a topic, then answer in that context. |
| `developer-tooling-answer.yaml` | Read a issue, draft a helpful reply. |
| `developer-tooling-classify-intent.yaml` | Classify a issue into one label. |
| `developer-tooling-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `developer-tooling-extract-to-json.yaml` | Extract structured fields from a issue as JSON. |
| `developer-tooling-language-route.yaml` | Detect the language of a issue; answer directly if English, else translate first. |
| `developer-tooling-moderation-gate.yaml` | Check a issue for policy issues before publishing. |
| `developer-tooling-score-gate.yaml` | Score a issue 1-5 for priority, then gate on the number. |
| `developer-tooling-sentiment-route.yaml` | Detect sentiment of a issue, escalate the negative ones. |
| `developer-tooling-summarize-then-decide.yaml` | Summarize a issue, then branch on whether it needs follow-up. |
| `developer-tooling-tag-enrich.yaml` | Produce a JSON list of topic tags for a issue. |
| `developer-tooling-translate-reply.yaml` | Translate a issue to English, then draft a reply. |
| `developer-tooling-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `devrel-faq-match-answer.yaml` | Match a question to a topic, then answer in that context. |
| `devrel-answer.yaml` | Read a question, draft a helpful reply. |
| `devrel-classify-intent.yaml` | Classify a question into one label. |
| `devrel-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `devrel-extract-to-json.yaml` | Extract structured fields from a question as JSON. |
| `devrel-language-route.yaml` | Detect the language of a question; answer directly if English, else translate first. |
| `devrel-moderation-gate.yaml` | Check a question for policy issues before publishing. |
| `devrel-score-gate.yaml` | Score a question 1-5 for priority, then gate on the number. |
| `devrel-sentiment-route.yaml` | Detect sentiment of a question, escalate the negative ones. |
| `devrel-summarize-then-decide.yaml` | Summarize a question, then branch on whether it needs follow-up. |
| `devrel-tag-enrich.yaml` | Produce a JSON list of topic tags for a question. |
| `devrel-translate-reply.yaml` | Translate a question to English, then draft a reply. |
| `devrel-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `e-commerce-faq-match-answer.yaml` | Match a review to a topic, then answer in that context. |
| `e-commerce-answer.yaml` | Read a review, draft a helpful reply. |
| `e-commerce-classify-intent.yaml` | Classify a review into one label. |
| `e-commerce-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `e-commerce-extract-to-json.yaml` | Extract structured fields from a review as JSON. |
| `e-commerce-language-route.yaml` | Detect the language of a review; answer directly if English, else translate first. |
| `e-commerce-moderation-gate.yaml` | Check a review for policy issues before publishing. |
| `e-commerce-score-gate.yaml` | Score a review 1-5 for priority, then gate on the number. |
| `e-commerce-sentiment-route.yaml` | Detect sentiment of a review, escalate the negative ones. |
| `e-commerce-summarize-then-decide.yaml` | Summarize a review, then branch on whether it needs follow-up. |
| `e-commerce-tag-enrich.yaml` | Produce a JSON list of topic tags for a review. |
| `e-commerce-translate-reply.yaml` | Translate a review to English, then draft a reply. |
| `e-commerce-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `education-faq-match-answer.yaml` | Match a question to a topic, then answer in that context. |
| `education-answer.yaml` | Read a question, draft a helpful reply. |
| `education-classify-intent.yaml` | Classify a question into one label. |
| `education-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `education-extract-to-json.yaml` | Extract structured fields from a question as JSON. |
| `education-language-route.yaml` | Detect the language of a question; answer directly if English, else translate first. |
| `education-moderation-gate.yaml` | Check a question for policy issues before publishing. |
| `education-score-gate.yaml` | Score a question 1-5 for priority, then gate on the number. |
| `education-sentiment-route.yaml` | Detect sentiment of a question, escalate the negative ones. |
| `education-summarize-then-decide.yaml` | Summarize a question, then branch on whether it needs follow-up. |
| `education-tag-enrich.yaml` | Produce a JSON list of topic tags for a question. |
| `education-translate-reply.yaml` | Translate a question to English, then draft a reply. |
| `education-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `finance-faq-match-answer.yaml` | Match a transaction to a topic, then answer in that context. |
| `finance-answer.yaml` | Read a transaction, draft a helpful reply. |
| `finance-classify-intent.yaml` | Classify a transaction into one label. |
| `finance-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `finance-extract-to-json.yaml` | Extract structured fields from a transaction as JSON. |
| `finance-language-route.yaml` | Detect the language of a transaction; answer directly if English, else translate first. |
| `finance-moderation-gate.yaml` | Check a transaction for policy issues before publishing. |
| `finance-score-gate.yaml` | Score a transaction 1-5 for priority, then gate on the number. |
| `finance-sentiment-route.yaml` | Detect sentiment of a transaction, escalate the negative ones. |
| `finance-summarize-then-decide.yaml` | Summarize a transaction, then branch on whether it needs follow-up. |
| `finance-tag-enrich.yaml` | Produce a JSON list of topic tags for a transaction. |
| `finance-translate-reply.yaml` | Translate a transaction to English, then draft a reply. |
| `finance-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `food-delivery-faq-match-answer.yaml` | Match a complaint to a topic, then answer in that context. |
| `food-delivery-answer.yaml` | Read a complaint, draft a helpful reply. |
| `food-delivery-classify-intent.yaml` | Classify a complaint into one label. |
| `food-delivery-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `food-delivery-extract-to-json.yaml` | Extract structured fields from a complaint as JSON. |
| `food-delivery-language-route.yaml` | Detect the language of a complaint; answer directly if English, else translate first. |
| `food-delivery-moderation-gate.yaml` | Check a complaint for policy issues before publishing. |
| `food-delivery-score-gate.yaml` | Score a complaint 1-5 for priority, then gate on the number. |
| `food-delivery-sentiment-route.yaml` | Detect sentiment of a complaint, escalate the negative ones. |
| `food-delivery-summarize-then-decide.yaml` | Summarize a complaint, then branch on whether it needs follow-up. |
| `food-delivery-tag-enrich.yaml` | Produce a JSON list of topic tags for a complaint. |
| `food-delivery-translate-reply.yaml` | Translate a complaint to English, then draft a reply. |
| `food-delivery-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `gaming-support-faq-match-answer.yaml` | Match a report to a topic, then answer in that context. |
| `gaming-support-answer.yaml` | Read a report, draft a helpful reply. |
| `gaming-support-classify-intent.yaml` | Classify a report into one label. |
| `gaming-support-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `gaming-support-extract-to-json.yaml` | Extract structured fields from a report as JSON. |
| `gaming-support-language-route.yaml` | Detect the language of a report; answer directly if English, else translate first. |
| `gaming-support-moderation-gate.yaml` | Check a report for policy issues before publishing. |
| `gaming-support-score-gate.yaml` | Score a report 1-5 for priority, then gate on the number. |
| `gaming-support-sentiment-route.yaml` | Detect sentiment of a report, escalate the negative ones. |
| `gaming-support-summarize-then-decide.yaml` | Summarize a report, then branch on whether it needs follow-up. |
| `gaming-support-tag-enrich.yaml` | Produce a JSON list of topic tags for a report. |
| `gaming-support-translate-reply.yaml` | Translate a report to English, then draft a reply. |
| `gaming-support-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `healthcare-intake-faq-match-answer.yaml` | Match a note to a topic, then answer in that context. |
| `healthcare-intake-answer.yaml` | Read a note, draft a helpful reply. |
| `healthcare-intake-classify-intent.yaml` | Classify a note into one label. |
| `healthcare-intake-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `healthcare-intake-extract-to-json.yaml` | Extract structured fields from a note as JSON. |
| `healthcare-intake-language-route.yaml` | Detect the language of a note; answer directly if English, else translate first. |
| `healthcare-intake-moderation-gate.yaml` | Check a note for policy issues before publishing. |
| `healthcare-intake-score-gate.yaml` | Score a note 1-5 for priority, then gate on the number. |
| `healthcare-intake-sentiment-route.yaml` | Detect sentiment of a note, escalate the negative ones. |
| `healthcare-intake-summarize-then-decide.yaml` | Summarize a note, then branch on whether it needs follow-up. |
| `healthcare-intake-tag-enrich.yaml` | Produce a JSON list of topic tags for a note. |
| `healthcare-intake-translate-reply.yaml` | Translate a note to English, then draft a reply. |
| `healthcare-intake-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `hr-faq-match-answer.yaml` | Match a feedback to a topic, then answer in that context. |
| `hr-answer.yaml` | Read a feedback, draft a helpful reply. |
| `hr-classify-intent.yaml` | Classify a feedback into one label. |
| `hr-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `hr-extract-to-json.yaml` | Extract structured fields from a feedback as JSON. |
| `hr-language-route.yaml` | Detect the language of a feedback; answer directly if English, else translate first. |
| `hr-moderation-gate.yaml` | Check a feedback for policy issues before publishing. |
| `hr-score-gate.yaml` | Score a feedback 1-5 for priority, then gate on the number. |
| `hr-sentiment-route.yaml` | Detect sentiment of a feedback, escalate the negative ones. |
| `hr-summarize-then-decide.yaml` | Summarize a feedback, then branch on whether it needs follow-up. |
| `hr-tag-enrich.yaml` | Produce a JSON list of topic tags for a feedback. |
| `hr-translate-reply.yaml` | Translate a feedback to English, then draft a reply. |
| `hr-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `insurance-faq-match-answer.yaml` | Match a claim to a topic, then answer in that context. |
| `insurance-answer.yaml` | Read a claim, draft a helpful reply. |
| `insurance-classify-intent.yaml` | Classify a claim into one label. |
| `insurance-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `insurance-extract-to-json.yaml` | Extract structured fields from a claim as JSON. |
| `insurance-language-route.yaml` | Detect the language of a claim; answer directly if English, else translate first. |
| `insurance-moderation-gate.yaml` | Check a claim for policy issues before publishing. |
| `insurance-score-gate.yaml` | Score a claim 1-5 for priority, then gate on the number. |
| `insurance-sentiment-route.yaml` | Detect sentiment of a claim, escalate the negative ones. |
| `insurance-summarize-then-decide.yaml` | Summarize a claim, then branch on whether it needs follow-up. |
| `insurance-tag-enrich.yaml` | Produce a JSON list of topic tags for a claim. |
| `insurance-translate-reply.yaml` | Translate a claim to English, then draft a reply. |
| `insurance-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `it-helpdesk-faq-match-answer.yaml` | Match a ticket to a topic, then answer in that context. |
| `it-helpdesk-answer.yaml` | Read a ticket, draft a helpful reply. |
| `it-helpdesk-classify-intent.yaml` | Classify a ticket into one label. |
| `it-helpdesk-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `it-helpdesk-extract-to-json.yaml` | Extract structured fields from a ticket as JSON. |
| `it-helpdesk-language-route.yaml` | Detect the language of a ticket; answer directly if English, else translate first. |
| `it-helpdesk-moderation-gate.yaml` | Check a ticket for policy issues before publishing. |
| `it-helpdesk-score-gate.yaml` | Score a ticket 1-5 for priority, then gate on the number. |
| `it-helpdesk-sentiment-route.yaml` | Detect sentiment of a ticket, escalate the negative ones. |
| `it-helpdesk-summarize-then-decide.yaml` | Summarize a ticket, then branch on whether it needs follow-up. |
| `it-helpdesk-tag-enrich.yaml` | Produce a JSON list of topic tags for a ticket. |
| `it-helpdesk-translate-reply.yaml` | Translate a ticket to English, then draft a reply. |
| `it-helpdesk-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `legal-intake-faq-match-answer.yaml` | Match a inquiry to a topic, then answer in that context. |
| `legal-intake-answer.yaml` | Read a inquiry, draft a helpful reply. |
| `legal-intake-classify-intent.yaml` | Classify a inquiry into one label. |
| `legal-intake-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `legal-intake-extract-to-json.yaml` | Extract structured fields from a inquiry as JSON. |
| `legal-intake-language-route.yaml` | Detect the language of a inquiry; answer directly if English, else translate first. |
| `legal-intake-moderation-gate.yaml` | Check a inquiry for policy issues before publishing. |
| `legal-intake-score-gate.yaml` | Score a inquiry 1-5 for priority, then gate on the number. |
| `legal-intake-sentiment-route.yaml` | Detect sentiment of a inquiry, escalate the negative ones. |
| `legal-intake-summarize-then-decide.yaml` | Summarize a inquiry, then branch on whether it needs follow-up. |
| `legal-intake-tag-enrich.yaml` | Produce a JSON list of topic tags for a inquiry. |
| `legal-intake-translate-reply.yaml` | Translate a inquiry to English, then draft a reply. |
| `legal-intake-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `logistics-faq-match-answer.yaml` | Match a shipment to a topic, then answer in that context. |
| `logistics-answer.yaml` | Read a shipment, draft a helpful reply. |
| `logistics-classify-intent.yaml` | Classify a shipment into one label. |
| `logistics-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `logistics-extract-to-json.yaml` | Extract structured fields from a shipment as JSON. |
| `logistics-language-route.yaml` | Detect the language of a shipment; answer directly if English, else translate first. |
| `logistics-moderation-gate.yaml` | Check a shipment for policy issues before publishing. |
| `logistics-score-gate.yaml` | Score a shipment 1-5 for priority, then gate on the number. |
| `logistics-sentiment-route.yaml` | Detect sentiment of a shipment, escalate the negative ones. |
| `logistics-summarize-then-decide.yaml` | Summarize a shipment, then branch on whether it needs follow-up. |
| `logistics-tag-enrich.yaml` | Produce a JSON list of topic tags for a shipment. |
| `logistics-translate-reply.yaml` | Translate a shipment to English, then draft a reply. |
| `logistics-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `marketing-faq-match-answer.yaml` | Match a brief to a topic, then answer in that context. |
| `marketing-answer.yaml` | Read a brief, draft a helpful reply. |
| `marketing-classify-intent.yaml` | Classify a brief into one label. |
| `marketing-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `marketing-extract-to-json.yaml` | Extract structured fields from a brief as JSON. |
| `marketing-language-route.yaml` | Detect the language of a brief; answer directly if English, else translate first. |
| `marketing-moderation-gate.yaml` | Check a brief for policy issues before publishing. |
| `marketing-score-gate.yaml` | Score a brief 1-5 for priority, then gate on the number. |
| `marketing-sentiment-route.yaml` | Detect sentiment of a brief, escalate the negative ones. |
| `marketing-summarize-then-decide.yaml` | Summarize a brief, then branch on whether it needs follow-up. |
| `marketing-tag-enrich.yaml` | Produce a JSON list of topic tags for a brief. |
| `marketing-translate-reply.yaml` | Translate a brief to English, then draft a reply. |
| `marketing-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `nonprofit-faq-match-answer.yaml` | Match a message to a topic, then answer in that context. |
| `nonprofit-answer.yaml` | Read a message, draft a helpful reply. |
| `nonprofit-classify-intent.yaml` | Classify a message into one label. |
| `nonprofit-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `nonprofit-extract-to-json.yaml` | Extract structured fields from a message as JSON. |
| `nonprofit-language-route.yaml` | Detect the language of a message; answer directly if English, else translate first. |
| `nonprofit-moderation-gate.yaml` | Check a message for policy issues before publishing. |
| `nonprofit-score-gate.yaml` | Score a message 1-5 for priority, then gate on the number. |
| `nonprofit-sentiment-route.yaml` | Detect sentiment of a message, escalate the negative ones. |
| `nonprofit-summarize-then-decide.yaml` | Summarize a message, then branch on whether it needs follow-up. |
| `nonprofit-tag-enrich.yaml` | Produce a JSON list of topic tags for a message. |
| `nonprofit-translate-reply.yaml` | Translate a message to English, then draft a reply. |
| `nonprofit-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `real-estate-faq-match-answer.yaml` | Match a listing to a topic, then answer in that context. |
| `real-estate-answer.yaml` | Read a listing, draft a helpful reply. |
| `real-estate-classify-intent.yaml` | Classify a listing into one label. |
| `real-estate-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `real-estate-extract-to-json.yaml` | Extract structured fields from a listing as JSON. |
| `real-estate-language-route.yaml` | Detect the language of a listing; answer directly if English, else translate first. |
| `real-estate-moderation-gate.yaml` | Check a listing for policy issues before publishing. |
| `real-estate-score-gate.yaml` | Score a listing 1-5 for priority, then gate on the number. |
| `real-estate-sentiment-route.yaml` | Detect sentiment of a listing, escalate the negative ones. |
| `real-estate-summarize-then-decide.yaml` | Summarize a listing, then branch on whether it needs follow-up. |
| `real-estate-tag-enrich.yaml` | Produce a JSON list of topic tags for a listing. |
| `real-estate-translate-reply.yaml` | Translate a listing to English, then draft a reply. |
| `real-estate-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `recruiting-faq-match-answer.yaml` | Match a resume to a topic, then answer in that context. |
| `recruiting-answer.yaml` | Read a resume, draft a helpful reply. |
| `recruiting-classify-intent.yaml` | Classify a resume into one label. |
| `recruiting-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `recruiting-extract-to-json.yaml` | Extract structured fields from a resume as JSON. |
| `recruiting-language-route.yaml` | Detect the language of a resume; answer directly if English, else translate first. |
| `recruiting-moderation-gate.yaml` | Check a resume for policy issues before publishing. |
| `recruiting-score-gate.yaml` | Score a resume 1-5 for priority, then gate on the number. |
| `recruiting-sentiment-route.yaml` | Detect sentiment of a resume, escalate the negative ones. |
| `recruiting-summarize-then-decide.yaml` | Summarize a resume, then branch on whether it needs follow-up. |
| `recruiting-tag-enrich.yaml` | Produce a JSON list of topic tags for a resume. |
| `recruiting-translate-reply.yaml` | Translate a resume to English, then draft a reply. |
| `recruiting-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `research-faq-match-answer.yaml` | Match a abstract to a topic, then answer in that context. |
| `research-answer.yaml` | Read a abstract, draft a helpful reply. |
| `research-classify-intent.yaml` | Classify a abstract into one label. |
| `research-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `research-extract-to-json.yaml` | Extract structured fields from a abstract as JSON. |
| `research-language-route.yaml` | Detect the language of a abstract; answer directly if English, else translate first. |
| `research-moderation-gate.yaml` | Check a abstract for policy issues before publishing. |
| `research-score-gate.yaml` | Score a abstract 1-5 for priority, then gate on the number. |
| `research-sentiment-route.yaml` | Detect sentiment of a abstract, escalate the negative ones. |
| `research-summarize-then-decide.yaml` | Summarize a abstract, then branch on whether it needs follow-up. |
| `research-tag-enrich.yaml` | Produce a JSON list of topic tags for a abstract. |
| `research-translate-reply.yaml` | Translate a abstract to English, then draft a reply. |
| `research-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `sales-lead-faq-match-answer.yaml` | Match a message to a topic, then answer in that context. |
| `sales-lead-answer.yaml` | Read a message, draft a helpful reply. |
| `sales-lead-classify-intent.yaml` | Classify a message into one label. |
| `sales-lead-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `sales-lead-extract-to-json.yaml` | Extract structured fields from a message as JSON. |
| `sales-lead-language-route.yaml` | Detect the language of a message; answer directly if English, else translate first. |
| `sales-lead-moderation-gate.yaml` | Check a message for policy issues before publishing. |
| `sales-lead-score-gate.yaml` | Score a message 1-5 for priority, then gate on the number. |
| `sales-lead-sentiment-route.yaml` | Detect sentiment of a message, escalate the negative ones. |
| `sales-lead-summarize-then-decide.yaml` | Summarize a message, then branch on whether it needs follow-up. |
| `sales-lead-tag-enrich.yaml` | Produce a JSON list of topic tags for a message. |
| `sales-lead-translate-reply.yaml` | Translate a message to English, then draft a reply. |
| `sales-lead-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
| `travel-faq-match-answer.yaml` | Match a request to a topic, then answer in that context. |
| `travel-answer.yaml` | Read a request, draft a helpful reply. |
| `travel-classify-intent.yaml` | Classify a request into one label. |
| `travel-draft-critique-revise.yaml` | Draft a reply, self-critique it, then produce a revised final. |
| `travel-extract-to-json.yaml` | Extract structured fields from a request as JSON. |
| `travel-language-route.yaml` | Detect the language of a request; answer directly if English, else translate first. |
| `travel-moderation-gate.yaml` | Check a request for policy issues before publishing. |
| `travel-score-gate.yaml` | Score a request 1-5 for priority, then gate on the number. |
| `travel-sentiment-route.yaml` | Detect sentiment of a request, escalate the negative ones. |
| `travel-summarize-then-decide.yaml` | Summarize a request, then branch on whether it needs follow-up. |
| `travel-tag-enrich.yaml` | Produce a JSON list of topic tags for a request. |
| `travel-translate-reply.yaml` | Translate a request to English, then draft a reply. |
| `travel-triage-route.yaml` | Draft a reply, then route urgent vs normal on a keyword check. |
