# every piece is a bet
After each piece, the model hands back a probability for **every** possible next piece — about 150,000 of them. `Alright` 40%, `Okay` 35%, `Let` 10%, and a long tail of almost-nothing. That list is what the **what it almost said** box draws.

The model does not pick. Something outside it has to choose one piece from that list, and then the whole thing runs again for the next piece.

The simplest chooser is **greedy**: always take the top one. That is what this wall runs (temperature 0). Ask the same question twice and you get the same answer, and every piece you see is honestly "the most likely one." When the top guess is 51% and the runner-up is 49%, you are watching it choose by a hair.
