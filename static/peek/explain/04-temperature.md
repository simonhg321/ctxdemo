# temperature
**Temperature** is the dial that lets the chooser gamble. At 0 it is greedy. Above 0 it rolls dice weighted by the odds: at 0.6 a 40% piece gets picked about 40% of the time, a 10% piece sometimes, a 0.1% piece almost never. Turn it up and the odds flatten, so the tail gets picked more — that is "creative," and also "wrong more often."

- **top-p** — only roll among the pieces that together cover, say, 95% of the odds; ignore the junk tail entirely.
- **top-k** — same idea by count: only the best k pieces are in the hat.
- **repetition penalty** — a small tax on any piece that has already appeared, so a rut gets shallower instead of deeper.

None of these change what the model *knows*. They only change how the one piece gets picked from the list it already made.
