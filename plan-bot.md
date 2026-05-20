Where I'd start (single bot, DMs — highest value, lowest effort):
Web-search-backed Q&A. This is the standout. A local 9B has no current knowledge, but routed through Open WebUI's API it can search and answer about today's news, prices, etc. — and it all runs on your PC, which is a real selling point over cloud bots. This one feature justifies the whole setup.
Summarize / TL;DR. Forward it an article or a long message, get the gist. Pairs naturally with web search ("summarize this URL").
Translate. Qwen handles 200+ languages well. Given where you are, an Uzbek ↔️ Russian ↔️ English bot in mixed-language group chats is genuinely useful and something the 9B is good at.
Rewrite / tone fixer. "Make this shorter / more formal / friendlier." Cheap, reliable, popular.
Chat-with-your-PDF (RAG). Upload a document to the bot, then ask about it — uses the /api/v1/files/ upload + the chat endpoint. Great for notes, manuals, contracts.
These four or five exercise your entire pipeline and the 9B handles them comfortably.
Guest-bot features (tag @yourbot in any group). Remember it only sees the tagged message and replies to it, not the whole chat — so design per-message tasks, not "read everything" tasks:
Group helper — people tag it with a question and get an answer without it lurking on the conversation (the privacy scoping is a feature).
Fact-check — tag it on a forwarded claim → web-search-backed "likely true/false because…".
Explain-this — tag on a confusing term or paragraph → plain-language explanation.
Quick tools — calculator, unit/currency conversion, regex check, "explain this code snippet."