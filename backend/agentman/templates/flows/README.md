# Demo flow gallery

432 bundled flow templates, browsable + searchable in the app's **New flow** picker. Each references the keyless **Demo Assistant (mock)** connection, so they run offline out of the box.

| Flow | Pattern | What it does |
|---|---|---|
| `banking-faq-match-answer.yaml` | FAQ match & answer | Match a request to a topic, then answer in that context. |
| `banking-action-items.yaml` | action items | Turn a request into a JSON list of action items. |
| `banking-answer.yaml` | answer | Read a request, draft a helpful reply. |
| `banking-classify-intent.yaml` | classify intent | Classify a request into one label. |
| `banking-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `banking-extract-to-json.yaml` | extract to JSON | Extract structured fields from a request as JSON. |
| `banking-keyword-extract.yaml` | keyword extract | Pull the top keywords from a request as a JSON array. |
| `banking-language-route.yaml` | language route | Detect the language of a request; answer directly if English, else translate first. |
| `banking-moderation-gate.yaml` | moderation gate | Check a request for policy issues before publishing. |
| `banking-redact-summarize.yaml` | redact & summarize | Redact personal data from a request, then summarize the rest. |
| `banking-score-gate.yaml` | score & gate | Score a request 1-5 for priority, then gate on the number. |
| `banking-sentiment-route.yaml` | sentiment route | Detect sentiment of a request, escalate the negative ones. |
| `banking-severity-tiers.yaml` | severity tiers | Classify severity of a request, then route across three tiers with chained checks. |
| `banking-summarize-then-decide.yaml` | summarize then decide | Summarize a request, then branch on whether it needs follow-up. |
| `banking-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a request. |
| `banking-tone-rewrite.yaml` | tone rewrite | Rewrite a request in a warm, professional tone. |
| `banking-translate-reply.yaml` | translate & reply | Translate a request to English, then draft a reply. |
| `banking-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `community-forum-faq-match-answer.yaml` | FAQ match & answer | Match a post to a topic, then answer in that context. |
| `community-forum-action-items.yaml` | action items | Turn a post into a JSON list of action items. |
| `community-forum-answer.yaml` | answer | Read a post, draft a helpful reply. |
| `community-forum-classify-intent.yaml` | classify intent | Classify a post into one label. |
| `community-forum-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `community-forum-extract-to-json.yaml` | extract to JSON | Extract structured fields from a post as JSON. |
| `community-forum-keyword-extract.yaml` | keyword extract | Pull the top keywords from a post as a JSON array. |
| `community-forum-language-route.yaml` | language route | Detect the language of a post; answer directly if English, else translate first. |
| `community-forum-moderation-gate.yaml` | moderation gate | Check a post for policy issues before publishing. |
| `community-forum-redact-summarize.yaml` | redact & summarize | Redact personal data from a post, then summarize the rest. |
| `community-forum-score-gate.yaml` | score & gate | Score a post 1-5 for priority, then gate on the number. |
| `community-forum-sentiment-route.yaml` | sentiment route | Detect sentiment of a post, escalate the negative ones. |
| `community-forum-severity-tiers.yaml` | severity tiers | Classify severity of a post, then route across three tiers with chained checks. |
| `community-forum-summarize-then-decide.yaml` | summarize then decide | Summarize a post, then branch on whether it needs follow-up. |
| `community-forum-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a post. |
| `community-forum-tone-rewrite.yaml` | tone rewrite | Rewrite a post in a warm, professional tone. |
| `community-forum-translate-reply.yaml` | translate & reply | Translate a post to English, then draft a reply. |
| `community-forum-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `content-moderation-faq-match-answer.yaml` | FAQ match & answer | Match a text to a topic, then answer in that context. |
| `content-moderation-action-items.yaml` | action items | Turn a text into a JSON list of action items. |
| `content-moderation-answer.yaml` | answer | Read a text, draft a helpful reply. |
| `content-moderation-classify-intent.yaml` | classify intent | Classify a text into one label. |
| `content-moderation-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `content-moderation-extract-to-json.yaml` | extract to JSON | Extract structured fields from a text as JSON. |
| `content-moderation-keyword-extract.yaml` | keyword extract | Pull the top keywords from a text as a JSON array. |
| `content-moderation-language-route.yaml` | language route | Detect the language of a text; answer directly if English, else translate first. |
| `content-moderation-moderation-gate.yaml` | moderation gate | Check a text for policy issues before publishing. |
| `content-moderation-redact-summarize.yaml` | redact & summarize | Redact personal data from a text, then summarize the rest. |
| `content-moderation-score-gate.yaml` | score & gate | Score a text 1-5 for priority, then gate on the number. |
| `content-moderation-sentiment-route.yaml` | sentiment route | Detect sentiment of a text, escalate the negative ones. |
| `content-moderation-severity-tiers.yaml` | severity tiers | Classify severity of a text, then route across three tiers with chained checks. |
| `content-moderation-summarize-then-decide.yaml` | summarize then decide | Summarize a text, then branch on whether it needs follow-up. |
| `content-moderation-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a text. |
| `content-moderation-tone-rewrite.yaml` | tone rewrite | Rewrite a text in a warm, professional tone. |
| `content-moderation-translate-reply.yaml` | translate & reply | Translate a text to English, then draft a reply. |
| `content-moderation-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `customer-support-faq-match-answer.yaml` | FAQ match & answer | Match a message to a topic, then answer in that context. |
| `customer-support-action-items.yaml` | action items | Turn a message into a JSON list of action items. |
| `customer-support-answer.yaml` | answer | Read a message, draft a helpful reply. |
| `customer-support-classify-intent.yaml` | classify intent | Classify a message into one label. |
| `customer-support-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `customer-support-extract-to-json.yaml` | extract to JSON | Extract structured fields from a message as JSON. |
| `customer-support-keyword-extract.yaml` | keyword extract | Pull the top keywords from a message as a JSON array. |
| `customer-support-language-route.yaml` | language route | Detect the language of a message; answer directly if English, else translate first. |
| `customer-support-moderation-gate.yaml` | moderation gate | Check a message for policy issues before publishing. |
| `customer-support-redact-summarize.yaml` | redact & summarize | Redact personal data from a message, then summarize the rest. |
| `customer-support-score-gate.yaml` | score & gate | Score a message 1-5 for priority, then gate on the number. |
| `customer-support-sentiment-route.yaml` | sentiment route | Detect sentiment of a message, escalate the negative ones. |
| `customer-support-severity-tiers.yaml` | severity tiers | Classify severity of a message, then route across three tiers with chained checks. |
| `customer-support-summarize-then-decide.yaml` | summarize then decide | Summarize a message, then branch on whether it needs follow-up. |
| `customer-support-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a message. |
| `customer-support-tone-rewrite.yaml` | tone rewrite | Rewrite a message in a warm, professional tone. |
| `customer-support-translate-reply.yaml` | translate & reply | Translate a message to English, then draft a reply. |
| `customer-support-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `developer-tooling-faq-match-answer.yaml` | FAQ match & answer | Match a issue to a topic, then answer in that context. |
| `developer-tooling-action-items.yaml` | action items | Turn a issue into a JSON list of action items. |
| `developer-tooling-answer.yaml` | answer | Read a issue, draft a helpful reply. |
| `developer-tooling-classify-intent.yaml` | classify intent | Classify a issue into one label. |
| `developer-tooling-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `developer-tooling-extract-to-json.yaml` | extract to JSON | Extract structured fields from a issue as JSON. |
| `developer-tooling-keyword-extract.yaml` | keyword extract | Pull the top keywords from a issue as a JSON array. |
| `developer-tooling-language-route.yaml` | language route | Detect the language of a issue; answer directly if English, else translate first. |
| `developer-tooling-moderation-gate.yaml` | moderation gate | Check a issue for policy issues before publishing. |
| `developer-tooling-redact-summarize.yaml` | redact & summarize | Redact personal data from a issue, then summarize the rest. |
| `developer-tooling-score-gate.yaml` | score & gate | Score a issue 1-5 for priority, then gate on the number. |
| `developer-tooling-sentiment-route.yaml` | sentiment route | Detect sentiment of a issue, escalate the negative ones. |
| `developer-tooling-severity-tiers.yaml` | severity tiers | Classify severity of a issue, then route across three tiers with chained checks. |
| `developer-tooling-summarize-then-decide.yaml` | summarize then decide | Summarize a issue, then branch on whether it needs follow-up. |
| `developer-tooling-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a issue. |
| `developer-tooling-tone-rewrite.yaml` | tone rewrite | Rewrite a issue in a warm, professional tone. |
| `developer-tooling-translate-reply.yaml` | translate & reply | Translate a issue to English, then draft a reply. |
| `developer-tooling-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `devrel-faq-match-answer.yaml` | FAQ match & answer | Match a question to a topic, then answer in that context. |
| `devrel-action-items.yaml` | action items | Turn a question into a JSON list of action items. |
| `devrel-answer.yaml` | answer | Read a question, draft a helpful reply. |
| `devrel-classify-intent.yaml` | classify intent | Classify a question into one label. |
| `devrel-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `devrel-extract-to-json.yaml` | extract to JSON | Extract structured fields from a question as JSON. |
| `devrel-keyword-extract.yaml` | keyword extract | Pull the top keywords from a question as a JSON array. |
| `devrel-language-route.yaml` | language route | Detect the language of a question; answer directly if English, else translate first. |
| `devrel-moderation-gate.yaml` | moderation gate | Check a question for policy issues before publishing. |
| `devrel-redact-summarize.yaml` | redact & summarize | Redact personal data from a question, then summarize the rest. |
| `devrel-score-gate.yaml` | score & gate | Score a question 1-5 for priority, then gate on the number. |
| `devrel-sentiment-route.yaml` | sentiment route | Detect sentiment of a question, escalate the negative ones. |
| `devrel-severity-tiers.yaml` | severity tiers | Classify severity of a question, then route across three tiers with chained checks. |
| `devrel-summarize-then-decide.yaml` | summarize then decide | Summarize a question, then branch on whether it needs follow-up. |
| `devrel-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a question. |
| `devrel-tone-rewrite.yaml` | tone rewrite | Rewrite a question in a warm, professional tone. |
| `devrel-translate-reply.yaml` | translate & reply | Translate a question to English, then draft a reply. |
| `devrel-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `e-commerce-faq-match-answer.yaml` | FAQ match & answer | Match a review to a topic, then answer in that context. |
| `e-commerce-action-items.yaml` | action items | Turn a review into a JSON list of action items. |
| `e-commerce-answer.yaml` | answer | Read a review, draft a helpful reply. |
| `e-commerce-classify-intent.yaml` | classify intent | Classify a review into one label. |
| `e-commerce-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `e-commerce-extract-to-json.yaml` | extract to JSON | Extract structured fields from a review as JSON. |
| `e-commerce-keyword-extract.yaml` | keyword extract | Pull the top keywords from a review as a JSON array. |
| `e-commerce-language-route.yaml` | language route | Detect the language of a review; answer directly if English, else translate first. |
| `e-commerce-moderation-gate.yaml` | moderation gate | Check a review for policy issues before publishing. |
| `e-commerce-redact-summarize.yaml` | redact & summarize | Redact personal data from a review, then summarize the rest. |
| `e-commerce-score-gate.yaml` | score & gate | Score a review 1-5 for priority, then gate on the number. |
| `e-commerce-sentiment-route.yaml` | sentiment route | Detect sentiment of a review, escalate the negative ones. |
| `e-commerce-severity-tiers.yaml` | severity tiers | Classify severity of a review, then route across three tiers with chained checks. |
| `e-commerce-summarize-then-decide.yaml` | summarize then decide | Summarize a review, then branch on whether it needs follow-up. |
| `e-commerce-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a review. |
| `e-commerce-tone-rewrite.yaml` | tone rewrite | Rewrite a review in a warm, professional tone. |
| `e-commerce-translate-reply.yaml` | translate & reply | Translate a review to English, then draft a reply. |
| `e-commerce-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `education-faq-match-answer.yaml` | FAQ match & answer | Match a question to a topic, then answer in that context. |
| `education-action-items.yaml` | action items | Turn a question into a JSON list of action items. |
| `education-answer.yaml` | answer | Read a question, draft a helpful reply. |
| `education-classify-intent.yaml` | classify intent | Classify a question into one label. |
| `education-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `education-extract-to-json.yaml` | extract to JSON | Extract structured fields from a question as JSON. |
| `education-keyword-extract.yaml` | keyword extract | Pull the top keywords from a question as a JSON array. |
| `education-language-route.yaml` | language route | Detect the language of a question; answer directly if English, else translate first. |
| `education-moderation-gate.yaml` | moderation gate | Check a question for policy issues before publishing. |
| `education-redact-summarize.yaml` | redact & summarize | Redact personal data from a question, then summarize the rest. |
| `education-score-gate.yaml` | score & gate | Score a question 1-5 for priority, then gate on the number. |
| `education-sentiment-route.yaml` | sentiment route | Detect sentiment of a question, escalate the negative ones. |
| `education-severity-tiers.yaml` | severity tiers | Classify severity of a question, then route across three tiers with chained checks. |
| `education-summarize-then-decide.yaml` | summarize then decide | Summarize a question, then branch on whether it needs follow-up. |
| `education-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a question. |
| `education-tone-rewrite.yaml` | tone rewrite | Rewrite a question in a warm, professional tone. |
| `education-translate-reply.yaml` | translate & reply | Translate a question to English, then draft a reply. |
| `education-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `finance-faq-match-answer.yaml` | FAQ match & answer | Match a transaction to a topic, then answer in that context. |
| `finance-action-items.yaml` | action items | Turn a transaction into a JSON list of action items. |
| `finance-answer.yaml` | answer | Read a transaction, draft a helpful reply. |
| `finance-classify-intent.yaml` | classify intent | Classify a transaction into one label. |
| `finance-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `finance-extract-to-json.yaml` | extract to JSON | Extract structured fields from a transaction as JSON. |
| `finance-keyword-extract.yaml` | keyword extract | Pull the top keywords from a transaction as a JSON array. |
| `finance-language-route.yaml` | language route | Detect the language of a transaction; answer directly if English, else translate first. |
| `finance-moderation-gate.yaml` | moderation gate | Check a transaction for policy issues before publishing. |
| `finance-redact-summarize.yaml` | redact & summarize | Redact personal data from a transaction, then summarize the rest. |
| `finance-score-gate.yaml` | score & gate | Score a transaction 1-5 for priority, then gate on the number. |
| `finance-sentiment-route.yaml` | sentiment route | Detect sentiment of a transaction, escalate the negative ones. |
| `finance-severity-tiers.yaml` | severity tiers | Classify severity of a transaction, then route across three tiers with chained checks. |
| `finance-summarize-then-decide.yaml` | summarize then decide | Summarize a transaction, then branch on whether it needs follow-up. |
| `finance-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a transaction. |
| `finance-tone-rewrite.yaml` | tone rewrite | Rewrite a transaction in a warm, professional tone. |
| `finance-translate-reply.yaml` | translate & reply | Translate a transaction to English, then draft a reply. |
| `finance-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `food-delivery-faq-match-answer.yaml` | FAQ match & answer | Match a complaint to a topic, then answer in that context. |
| `food-delivery-action-items.yaml` | action items | Turn a complaint into a JSON list of action items. |
| `food-delivery-answer.yaml` | answer | Read a complaint, draft a helpful reply. |
| `food-delivery-classify-intent.yaml` | classify intent | Classify a complaint into one label. |
| `food-delivery-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `food-delivery-extract-to-json.yaml` | extract to JSON | Extract structured fields from a complaint as JSON. |
| `food-delivery-keyword-extract.yaml` | keyword extract | Pull the top keywords from a complaint as a JSON array. |
| `food-delivery-language-route.yaml` | language route | Detect the language of a complaint; answer directly if English, else translate first. |
| `food-delivery-moderation-gate.yaml` | moderation gate | Check a complaint for policy issues before publishing. |
| `food-delivery-redact-summarize.yaml` | redact & summarize | Redact personal data from a complaint, then summarize the rest. |
| `food-delivery-score-gate.yaml` | score & gate | Score a complaint 1-5 for priority, then gate on the number. |
| `food-delivery-sentiment-route.yaml` | sentiment route | Detect sentiment of a complaint, escalate the negative ones. |
| `food-delivery-severity-tiers.yaml` | severity tiers | Classify severity of a complaint, then route across three tiers with chained checks. |
| `food-delivery-summarize-then-decide.yaml` | summarize then decide | Summarize a complaint, then branch on whether it needs follow-up. |
| `food-delivery-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a complaint. |
| `food-delivery-tone-rewrite.yaml` | tone rewrite | Rewrite a complaint in a warm, professional tone. |
| `food-delivery-translate-reply.yaml` | translate & reply | Translate a complaint to English, then draft a reply. |
| `food-delivery-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `gaming-support-faq-match-answer.yaml` | FAQ match & answer | Match a report to a topic, then answer in that context. |
| `gaming-support-action-items.yaml` | action items | Turn a report into a JSON list of action items. |
| `gaming-support-answer.yaml` | answer | Read a report, draft a helpful reply. |
| `gaming-support-classify-intent.yaml` | classify intent | Classify a report into one label. |
| `gaming-support-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `gaming-support-extract-to-json.yaml` | extract to JSON | Extract structured fields from a report as JSON. |
| `gaming-support-keyword-extract.yaml` | keyword extract | Pull the top keywords from a report as a JSON array. |
| `gaming-support-language-route.yaml` | language route | Detect the language of a report; answer directly if English, else translate first. |
| `gaming-support-moderation-gate.yaml` | moderation gate | Check a report for policy issues before publishing. |
| `gaming-support-redact-summarize.yaml` | redact & summarize | Redact personal data from a report, then summarize the rest. |
| `gaming-support-score-gate.yaml` | score & gate | Score a report 1-5 for priority, then gate on the number. |
| `gaming-support-sentiment-route.yaml` | sentiment route | Detect sentiment of a report, escalate the negative ones. |
| `gaming-support-severity-tiers.yaml` | severity tiers | Classify severity of a report, then route across three tiers with chained checks. |
| `gaming-support-summarize-then-decide.yaml` | summarize then decide | Summarize a report, then branch on whether it needs follow-up. |
| `gaming-support-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a report. |
| `gaming-support-tone-rewrite.yaml` | tone rewrite | Rewrite a report in a warm, professional tone. |
| `gaming-support-translate-reply.yaml` | translate & reply | Translate a report to English, then draft a reply. |
| `gaming-support-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `healthcare-intake-faq-match-answer.yaml` | FAQ match & answer | Match a note to a topic, then answer in that context. |
| `healthcare-intake-action-items.yaml` | action items | Turn a note into a JSON list of action items. |
| `healthcare-intake-answer.yaml` | answer | Read a note, draft a helpful reply. |
| `healthcare-intake-classify-intent.yaml` | classify intent | Classify a note into one label. |
| `healthcare-intake-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `healthcare-intake-extract-to-json.yaml` | extract to JSON | Extract structured fields from a note as JSON. |
| `healthcare-intake-keyword-extract.yaml` | keyword extract | Pull the top keywords from a note as a JSON array. |
| `healthcare-intake-language-route.yaml` | language route | Detect the language of a note; answer directly if English, else translate first. |
| `healthcare-intake-moderation-gate.yaml` | moderation gate | Check a note for policy issues before publishing. |
| `healthcare-intake-redact-summarize.yaml` | redact & summarize | Redact personal data from a note, then summarize the rest. |
| `healthcare-intake-score-gate.yaml` | score & gate | Score a note 1-5 for priority, then gate on the number. |
| `healthcare-intake-sentiment-route.yaml` | sentiment route | Detect sentiment of a note, escalate the negative ones. |
| `healthcare-intake-severity-tiers.yaml` | severity tiers | Classify severity of a note, then route across three tiers with chained checks. |
| `healthcare-intake-summarize-then-decide.yaml` | summarize then decide | Summarize a note, then branch on whether it needs follow-up. |
| `healthcare-intake-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a note. |
| `healthcare-intake-tone-rewrite.yaml` | tone rewrite | Rewrite a note in a warm, professional tone. |
| `healthcare-intake-translate-reply.yaml` | translate & reply | Translate a note to English, then draft a reply. |
| `healthcare-intake-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `hr-faq-match-answer.yaml` | FAQ match & answer | Match a feedback to a topic, then answer in that context. |
| `hr-action-items.yaml` | action items | Turn a feedback into a JSON list of action items. |
| `hr-answer.yaml` | answer | Read a feedback, draft a helpful reply. |
| `hr-classify-intent.yaml` | classify intent | Classify a feedback into one label. |
| `hr-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `hr-extract-to-json.yaml` | extract to JSON | Extract structured fields from a feedback as JSON. |
| `hr-keyword-extract.yaml` | keyword extract | Pull the top keywords from a feedback as a JSON array. |
| `hr-language-route.yaml` | language route | Detect the language of a feedback; answer directly if English, else translate first. |
| `hr-moderation-gate.yaml` | moderation gate | Check a feedback for policy issues before publishing. |
| `hr-redact-summarize.yaml` | redact & summarize | Redact personal data from a feedback, then summarize the rest. |
| `hr-score-gate.yaml` | score & gate | Score a feedback 1-5 for priority, then gate on the number. |
| `hr-sentiment-route.yaml` | sentiment route | Detect sentiment of a feedback, escalate the negative ones. |
| `hr-severity-tiers.yaml` | severity tiers | Classify severity of a feedback, then route across three tiers with chained checks. |
| `hr-summarize-then-decide.yaml` | summarize then decide | Summarize a feedback, then branch on whether it needs follow-up. |
| `hr-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a feedback. |
| `hr-tone-rewrite.yaml` | tone rewrite | Rewrite a feedback in a warm, professional tone. |
| `hr-translate-reply.yaml` | translate & reply | Translate a feedback to English, then draft a reply. |
| `hr-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `insurance-faq-match-answer.yaml` | FAQ match & answer | Match a claim to a topic, then answer in that context. |
| `insurance-action-items.yaml` | action items | Turn a claim into a JSON list of action items. |
| `insurance-answer.yaml` | answer | Read a claim, draft a helpful reply. |
| `insurance-classify-intent.yaml` | classify intent | Classify a claim into one label. |
| `insurance-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `insurance-extract-to-json.yaml` | extract to JSON | Extract structured fields from a claim as JSON. |
| `insurance-keyword-extract.yaml` | keyword extract | Pull the top keywords from a claim as a JSON array. |
| `insurance-language-route.yaml` | language route | Detect the language of a claim; answer directly if English, else translate first. |
| `insurance-moderation-gate.yaml` | moderation gate | Check a claim for policy issues before publishing. |
| `insurance-redact-summarize.yaml` | redact & summarize | Redact personal data from a claim, then summarize the rest. |
| `insurance-score-gate.yaml` | score & gate | Score a claim 1-5 for priority, then gate on the number. |
| `insurance-sentiment-route.yaml` | sentiment route | Detect sentiment of a claim, escalate the negative ones. |
| `insurance-severity-tiers.yaml` | severity tiers | Classify severity of a claim, then route across three tiers with chained checks. |
| `insurance-summarize-then-decide.yaml` | summarize then decide | Summarize a claim, then branch on whether it needs follow-up. |
| `insurance-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a claim. |
| `insurance-tone-rewrite.yaml` | tone rewrite | Rewrite a claim in a warm, professional tone. |
| `insurance-translate-reply.yaml` | translate & reply | Translate a claim to English, then draft a reply. |
| `insurance-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `it-helpdesk-faq-match-answer.yaml` | FAQ match & answer | Match a ticket to a topic, then answer in that context. |
| `it-helpdesk-action-items.yaml` | action items | Turn a ticket into a JSON list of action items. |
| `it-helpdesk-answer.yaml` | answer | Read a ticket, draft a helpful reply. |
| `it-helpdesk-classify-intent.yaml` | classify intent | Classify a ticket into one label. |
| `it-helpdesk-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `it-helpdesk-extract-to-json.yaml` | extract to JSON | Extract structured fields from a ticket as JSON. |
| `it-helpdesk-keyword-extract.yaml` | keyword extract | Pull the top keywords from a ticket as a JSON array. |
| `it-helpdesk-language-route.yaml` | language route | Detect the language of a ticket; answer directly if English, else translate first. |
| `it-helpdesk-moderation-gate.yaml` | moderation gate | Check a ticket for policy issues before publishing. |
| `it-helpdesk-redact-summarize.yaml` | redact & summarize | Redact personal data from a ticket, then summarize the rest. |
| `it-helpdesk-score-gate.yaml` | score & gate | Score a ticket 1-5 for priority, then gate on the number. |
| `it-helpdesk-sentiment-route.yaml` | sentiment route | Detect sentiment of a ticket, escalate the negative ones. |
| `it-helpdesk-severity-tiers.yaml` | severity tiers | Classify severity of a ticket, then route across three tiers with chained checks. |
| `it-helpdesk-summarize-then-decide.yaml` | summarize then decide | Summarize a ticket, then branch on whether it needs follow-up. |
| `it-helpdesk-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a ticket. |
| `it-helpdesk-tone-rewrite.yaml` | tone rewrite | Rewrite a ticket in a warm, professional tone. |
| `it-helpdesk-translate-reply.yaml` | translate & reply | Translate a ticket to English, then draft a reply. |
| `it-helpdesk-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `legal-intake-faq-match-answer.yaml` | FAQ match & answer | Match a inquiry to a topic, then answer in that context. |
| `legal-intake-action-items.yaml` | action items | Turn a inquiry into a JSON list of action items. |
| `legal-intake-answer.yaml` | answer | Read a inquiry, draft a helpful reply. |
| `legal-intake-classify-intent.yaml` | classify intent | Classify a inquiry into one label. |
| `legal-intake-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `legal-intake-extract-to-json.yaml` | extract to JSON | Extract structured fields from a inquiry as JSON. |
| `legal-intake-keyword-extract.yaml` | keyword extract | Pull the top keywords from a inquiry as a JSON array. |
| `legal-intake-language-route.yaml` | language route | Detect the language of a inquiry; answer directly if English, else translate first. |
| `legal-intake-moderation-gate.yaml` | moderation gate | Check a inquiry for policy issues before publishing. |
| `legal-intake-redact-summarize.yaml` | redact & summarize | Redact personal data from a inquiry, then summarize the rest. |
| `legal-intake-score-gate.yaml` | score & gate | Score a inquiry 1-5 for priority, then gate on the number. |
| `legal-intake-sentiment-route.yaml` | sentiment route | Detect sentiment of a inquiry, escalate the negative ones. |
| `legal-intake-severity-tiers.yaml` | severity tiers | Classify severity of a inquiry, then route across three tiers with chained checks. |
| `legal-intake-summarize-then-decide.yaml` | summarize then decide | Summarize a inquiry, then branch on whether it needs follow-up. |
| `legal-intake-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a inquiry. |
| `legal-intake-tone-rewrite.yaml` | tone rewrite | Rewrite a inquiry in a warm, professional tone. |
| `legal-intake-translate-reply.yaml` | translate & reply | Translate a inquiry to English, then draft a reply. |
| `legal-intake-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `logistics-faq-match-answer.yaml` | FAQ match & answer | Match a shipment to a topic, then answer in that context. |
| `logistics-action-items.yaml` | action items | Turn a shipment into a JSON list of action items. |
| `logistics-answer.yaml` | answer | Read a shipment, draft a helpful reply. |
| `logistics-classify-intent.yaml` | classify intent | Classify a shipment into one label. |
| `logistics-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `logistics-extract-to-json.yaml` | extract to JSON | Extract structured fields from a shipment as JSON. |
| `logistics-keyword-extract.yaml` | keyword extract | Pull the top keywords from a shipment as a JSON array. |
| `logistics-language-route.yaml` | language route | Detect the language of a shipment; answer directly if English, else translate first. |
| `logistics-moderation-gate.yaml` | moderation gate | Check a shipment for policy issues before publishing. |
| `logistics-redact-summarize.yaml` | redact & summarize | Redact personal data from a shipment, then summarize the rest. |
| `logistics-score-gate.yaml` | score & gate | Score a shipment 1-5 for priority, then gate on the number. |
| `logistics-sentiment-route.yaml` | sentiment route | Detect sentiment of a shipment, escalate the negative ones. |
| `logistics-severity-tiers.yaml` | severity tiers | Classify severity of a shipment, then route across three tiers with chained checks. |
| `logistics-summarize-then-decide.yaml` | summarize then decide | Summarize a shipment, then branch on whether it needs follow-up. |
| `logistics-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a shipment. |
| `logistics-tone-rewrite.yaml` | tone rewrite | Rewrite a shipment in a warm, professional tone. |
| `logistics-translate-reply.yaml` | translate & reply | Translate a shipment to English, then draft a reply. |
| `logistics-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `marketing-faq-match-answer.yaml` | FAQ match & answer | Match a brief to a topic, then answer in that context. |
| `marketing-action-items.yaml` | action items | Turn a brief into a JSON list of action items. |
| `marketing-answer.yaml` | answer | Read a brief, draft a helpful reply. |
| `marketing-classify-intent.yaml` | classify intent | Classify a brief into one label. |
| `marketing-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `marketing-extract-to-json.yaml` | extract to JSON | Extract structured fields from a brief as JSON. |
| `marketing-keyword-extract.yaml` | keyword extract | Pull the top keywords from a brief as a JSON array. |
| `marketing-language-route.yaml` | language route | Detect the language of a brief; answer directly if English, else translate first. |
| `marketing-moderation-gate.yaml` | moderation gate | Check a brief for policy issues before publishing. |
| `marketing-redact-summarize.yaml` | redact & summarize | Redact personal data from a brief, then summarize the rest. |
| `marketing-score-gate.yaml` | score & gate | Score a brief 1-5 for priority, then gate on the number. |
| `marketing-sentiment-route.yaml` | sentiment route | Detect sentiment of a brief, escalate the negative ones. |
| `marketing-severity-tiers.yaml` | severity tiers | Classify severity of a brief, then route across three tiers with chained checks. |
| `marketing-summarize-then-decide.yaml` | summarize then decide | Summarize a brief, then branch on whether it needs follow-up. |
| `marketing-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a brief. |
| `marketing-tone-rewrite.yaml` | tone rewrite | Rewrite a brief in a warm, professional tone. |
| `marketing-translate-reply.yaml` | translate & reply | Translate a brief to English, then draft a reply. |
| `marketing-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `nonprofit-faq-match-answer.yaml` | FAQ match & answer | Match a message to a topic, then answer in that context. |
| `nonprofit-action-items.yaml` | action items | Turn a message into a JSON list of action items. |
| `nonprofit-answer.yaml` | answer | Read a message, draft a helpful reply. |
| `nonprofit-classify-intent.yaml` | classify intent | Classify a message into one label. |
| `nonprofit-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `nonprofit-extract-to-json.yaml` | extract to JSON | Extract structured fields from a message as JSON. |
| `nonprofit-keyword-extract.yaml` | keyword extract | Pull the top keywords from a message as a JSON array. |
| `nonprofit-language-route.yaml` | language route | Detect the language of a message; answer directly if English, else translate first. |
| `nonprofit-moderation-gate.yaml` | moderation gate | Check a message for policy issues before publishing. |
| `nonprofit-redact-summarize.yaml` | redact & summarize | Redact personal data from a message, then summarize the rest. |
| `nonprofit-score-gate.yaml` | score & gate | Score a message 1-5 for priority, then gate on the number. |
| `nonprofit-sentiment-route.yaml` | sentiment route | Detect sentiment of a message, escalate the negative ones. |
| `nonprofit-severity-tiers.yaml` | severity tiers | Classify severity of a message, then route across three tiers with chained checks. |
| `nonprofit-summarize-then-decide.yaml` | summarize then decide | Summarize a message, then branch on whether it needs follow-up. |
| `nonprofit-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a message. |
| `nonprofit-tone-rewrite.yaml` | tone rewrite | Rewrite a message in a warm, professional tone. |
| `nonprofit-translate-reply.yaml` | translate & reply | Translate a message to English, then draft a reply. |
| `nonprofit-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `real-estate-faq-match-answer.yaml` | FAQ match & answer | Match a listing to a topic, then answer in that context. |
| `real-estate-action-items.yaml` | action items | Turn a listing into a JSON list of action items. |
| `real-estate-answer.yaml` | answer | Read a listing, draft a helpful reply. |
| `real-estate-classify-intent.yaml` | classify intent | Classify a listing into one label. |
| `real-estate-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `real-estate-extract-to-json.yaml` | extract to JSON | Extract structured fields from a listing as JSON. |
| `real-estate-keyword-extract.yaml` | keyword extract | Pull the top keywords from a listing as a JSON array. |
| `real-estate-language-route.yaml` | language route | Detect the language of a listing; answer directly if English, else translate first. |
| `real-estate-moderation-gate.yaml` | moderation gate | Check a listing for policy issues before publishing. |
| `real-estate-redact-summarize.yaml` | redact & summarize | Redact personal data from a listing, then summarize the rest. |
| `real-estate-score-gate.yaml` | score & gate | Score a listing 1-5 for priority, then gate on the number. |
| `real-estate-sentiment-route.yaml` | sentiment route | Detect sentiment of a listing, escalate the negative ones. |
| `real-estate-severity-tiers.yaml` | severity tiers | Classify severity of a listing, then route across three tiers with chained checks. |
| `real-estate-summarize-then-decide.yaml` | summarize then decide | Summarize a listing, then branch on whether it needs follow-up. |
| `real-estate-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a listing. |
| `real-estate-tone-rewrite.yaml` | tone rewrite | Rewrite a listing in a warm, professional tone. |
| `real-estate-translate-reply.yaml` | translate & reply | Translate a listing to English, then draft a reply. |
| `real-estate-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `recruiting-faq-match-answer.yaml` | FAQ match & answer | Match a resume to a topic, then answer in that context. |
| `recruiting-action-items.yaml` | action items | Turn a resume into a JSON list of action items. |
| `recruiting-answer.yaml` | answer | Read a resume, draft a helpful reply. |
| `recruiting-classify-intent.yaml` | classify intent | Classify a resume into one label. |
| `recruiting-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `recruiting-extract-to-json.yaml` | extract to JSON | Extract structured fields from a resume as JSON. |
| `recruiting-keyword-extract.yaml` | keyword extract | Pull the top keywords from a resume as a JSON array. |
| `recruiting-language-route.yaml` | language route | Detect the language of a resume; answer directly if English, else translate first. |
| `recruiting-moderation-gate.yaml` | moderation gate | Check a resume for policy issues before publishing. |
| `recruiting-redact-summarize.yaml` | redact & summarize | Redact personal data from a resume, then summarize the rest. |
| `recruiting-score-gate.yaml` | score & gate | Score a resume 1-5 for priority, then gate on the number. |
| `recruiting-sentiment-route.yaml` | sentiment route | Detect sentiment of a resume, escalate the negative ones. |
| `recruiting-severity-tiers.yaml` | severity tiers | Classify severity of a resume, then route across three tiers with chained checks. |
| `recruiting-summarize-then-decide.yaml` | summarize then decide | Summarize a resume, then branch on whether it needs follow-up. |
| `recruiting-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a resume. |
| `recruiting-tone-rewrite.yaml` | tone rewrite | Rewrite a resume in a warm, professional tone. |
| `recruiting-translate-reply.yaml` | translate & reply | Translate a resume to English, then draft a reply. |
| `recruiting-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `research-faq-match-answer.yaml` | FAQ match & answer | Match a abstract to a topic, then answer in that context. |
| `research-action-items.yaml` | action items | Turn a abstract into a JSON list of action items. |
| `research-answer.yaml` | answer | Read a abstract, draft a helpful reply. |
| `research-classify-intent.yaml` | classify intent | Classify a abstract into one label. |
| `research-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `research-extract-to-json.yaml` | extract to JSON | Extract structured fields from a abstract as JSON. |
| `research-keyword-extract.yaml` | keyword extract | Pull the top keywords from a abstract as a JSON array. |
| `research-language-route.yaml` | language route | Detect the language of a abstract; answer directly if English, else translate first. |
| `research-moderation-gate.yaml` | moderation gate | Check a abstract for policy issues before publishing. |
| `research-redact-summarize.yaml` | redact & summarize | Redact personal data from a abstract, then summarize the rest. |
| `research-score-gate.yaml` | score & gate | Score a abstract 1-5 for priority, then gate on the number. |
| `research-sentiment-route.yaml` | sentiment route | Detect sentiment of a abstract, escalate the negative ones. |
| `research-severity-tiers.yaml` | severity tiers | Classify severity of a abstract, then route across three tiers with chained checks. |
| `research-summarize-then-decide.yaml` | summarize then decide | Summarize a abstract, then branch on whether it needs follow-up. |
| `research-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a abstract. |
| `research-tone-rewrite.yaml` | tone rewrite | Rewrite a abstract in a warm, professional tone. |
| `research-translate-reply.yaml` | translate & reply | Translate a abstract to English, then draft a reply. |
| `research-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `sales-lead-faq-match-answer.yaml` | FAQ match & answer | Match a message to a topic, then answer in that context. |
| `sales-lead-action-items.yaml` | action items | Turn a message into a JSON list of action items. |
| `sales-lead-answer.yaml` | answer | Read a message, draft a helpful reply. |
| `sales-lead-classify-intent.yaml` | classify intent | Classify a message into one label. |
| `sales-lead-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `sales-lead-extract-to-json.yaml` | extract to JSON | Extract structured fields from a message as JSON. |
| `sales-lead-keyword-extract.yaml` | keyword extract | Pull the top keywords from a message as a JSON array. |
| `sales-lead-language-route.yaml` | language route | Detect the language of a message; answer directly if English, else translate first. |
| `sales-lead-moderation-gate.yaml` | moderation gate | Check a message for policy issues before publishing. |
| `sales-lead-redact-summarize.yaml` | redact & summarize | Redact personal data from a message, then summarize the rest. |
| `sales-lead-score-gate.yaml` | score & gate | Score a message 1-5 for priority, then gate on the number. |
| `sales-lead-sentiment-route.yaml` | sentiment route | Detect sentiment of a message, escalate the negative ones. |
| `sales-lead-severity-tiers.yaml` | severity tiers | Classify severity of a message, then route across three tiers with chained checks. |
| `sales-lead-summarize-then-decide.yaml` | summarize then decide | Summarize a message, then branch on whether it needs follow-up. |
| `sales-lead-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a message. |
| `sales-lead-tone-rewrite.yaml` | tone rewrite | Rewrite a message in a warm, professional tone. |
| `sales-lead-translate-reply.yaml` | translate & reply | Translate a message to English, then draft a reply. |
| `sales-lead-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
| `travel-faq-match-answer.yaml` | FAQ match & answer | Match a request to a topic, then answer in that context. |
| `travel-action-items.yaml` | action items | Turn a request into a JSON list of action items. |
| `travel-answer.yaml` | answer | Read a request, draft a helpful reply. |
| `travel-classify-intent.yaml` | classify intent | Classify a request into one label. |
| `travel-draft-critique-revise.yaml` | draft, critique, revise | Draft a reply, self-critique it, then produce a revised final. |
| `travel-extract-to-json.yaml` | extract to JSON | Extract structured fields from a request as JSON. |
| `travel-keyword-extract.yaml` | keyword extract | Pull the top keywords from a request as a JSON array. |
| `travel-language-route.yaml` | language route | Detect the language of a request; answer directly if English, else translate first. |
| `travel-moderation-gate.yaml` | moderation gate | Check a request for policy issues before publishing. |
| `travel-redact-summarize.yaml` | redact & summarize | Redact personal data from a request, then summarize the rest. |
| `travel-score-gate.yaml` | score & gate | Score a request 1-5 for priority, then gate on the number. |
| `travel-sentiment-route.yaml` | sentiment route | Detect sentiment of a request, escalate the negative ones. |
| `travel-severity-tiers.yaml` | severity tiers | Classify severity of a request, then route across three tiers with chained checks. |
| `travel-summarize-then-decide.yaml` | summarize then decide | Summarize a request, then branch on whether it needs follow-up. |
| `travel-tag-enrich.yaml` | tag & enrich | Produce a JSON list of topic tags for a request. |
| `travel-tone-rewrite.yaml` | tone rewrite | Rewrite a request in a warm, professional tone. |
| `travel-translate-reply.yaml` | translate & reply | Translate a request to English, then draft a reply. |
| `travel-triage-route.yaml` | triage & route | Draft a reply, then route urgent vs normal on a keyword check. |
