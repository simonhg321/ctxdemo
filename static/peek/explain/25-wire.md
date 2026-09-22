# how we know
Nothing here is guessed from the outside and nothing is wired into the model. The ask box sends the server one ordinary chat request — the same kind every chat app sends — with two extra flags: `logprobs: true` and `top_logprobs: 5`.

The server already computes a probability for every possible next piece; that is how it picks one. The flags just tell it to **keep the numbers** for the piece it chose and the five runners-up, and send them back beside the text.

- **we send** — the instructions (the persona), your question, and the two flags.
- **it answers** — the text, plus one entry per piece: the piece, its probability, and what it almost said.

Press **how do we know?** under the personas to see the real request and reply for the last answer, byte for byte.
