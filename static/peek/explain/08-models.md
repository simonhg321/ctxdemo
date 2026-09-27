# the models
Right now the wall is running **{{model}}**. Tap the name on the model tile (with the password) to swap in another. Every one below is open-weights from Hugging Face and fits on this one 20 GB card; a swap restarts the model server, about a minute if the weights are already here.

- **Qwen3 8B** (Alibaba, 2025) — the house model. Dense 8B, served in FP8, thinking turned off so you see the answer form directly. Everything else is measured against this one.
- **Qwen3 14B** (Alibaba, 2025) — the same family, nearly twice the size, squeezed to 4-bit so it fits. Watch whether "bigger" shows up as fewer coin-flips.
- **Qwen3 4B** (Alibaba, 2025) — half the house model. Faster, more hesitation on the hard ones.
- **Qwen2.5 7B** (Alibaba, 2024) — last year's Qwen, 4-bit. A yardstick for how much one year moved.
- **Gemma 4 12B** (Google, 2026) — Google's open family, 4-bit. A different lineage from Qwen: same question, different upbringing.
- **Gemma 4 E4B** (Google, 2026) — the small Gemma, built for phones and laptops. Quick, and honest about what it does not know.
- **gpt-oss 20B** (OpenAI, 2025) — OpenAI's open-weights model, a mixture of experts: 20B on disk, about 4B awake per token. Reasons out loud before it answers.
- **Nemotron 3 Nano 4B** (NVIDIA, 2026) — a hybrid architecture, part transformer, part state-space. Same dials, different machinery under them. Thinks in `<think>` tags first.
- **Ornith 1.5 9B** and **NeoHorse 1 9B** (community, 2026) — two of this month's most-downloaded fine-tunes, both built on Qwen3.5, both squeezed to fit. They think in `<think>` tags first.
- **MiniCPM 5 2B** (OpenBMB, 2026) — the smallest one here. Thinks in `<think>` tags first. Good for watching confidence collapse on questions the big ones shrug off.
- **DeepSeek R1 7B** (DeepSeek, 2025) — a reasoning model: it thinks in `<think>` tags first. Loops sometimes under greedy, so it runs on a 2,000-token leash and has no web tool.
- **Phi-4 mini** (Microsoft, 2025) — 3.8B, trained heavily on textbook-style data.
- **Granite 3.3 2B** (IBM, 2025) — IBM's small enterprise model. Plain, careful, rarely surprising.

Not on the list: anything over about 18 GB of weights (the Qwen 27B, GLM, DeepSeek V4, the 100B+ crowd). Those need a bigger card than this one.
