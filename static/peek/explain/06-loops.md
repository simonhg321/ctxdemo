# why it loops
Picture the model right after writing `Alright,`. Its top guess for the next piece is `Alright` at 30%. Greedy takes it. Now the text reads `Alright, Alright,` and the model, seeing a pattern, is even surer: 60%. Greedy takes it again. Every repeat makes the next repeat more likely, and nothing ever breaks the cycle because the chooser only ever takes the favorite.

A little temperature is the escape hatch: on one of those turns the dice land on `so` or `the` and the model climbs out. Reasoning models like DeepSeek R1 are extra prone to this — they were trained to think in long rambling paragraphs at temperature 0.6, so under greedy their habits collapse into a rut. Their own model card says so.

The **leash** (max pieces) is the only other brake: the server cuts the answer off after N pieces no matter what. A model in a loop runs happily to the leash. One question can burn 10,000 pieces — about five minutes of the GPU — while everyone else in the room waits behind it.
