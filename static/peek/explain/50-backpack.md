# the backpack
Everything the model can use to answer has to fit in one bag: the instructions, every question and answer so far, and its own answer as it writes it. That bag is the **context window**; the wall calls it the backpack.

It is measured in pieces. This wall gives the model a small one on purpose (a few thousand pieces) so you can watch it fill in a short conversation. When it is nearly full the model has to **compact** — write itself a short summary and drop the rest — and anything not in the summary is gone. Ask the "every US president" question and watch the tile climb; when it compacts, the line under the ask box says so.

The number in the tiles is how full the bag is right now.
