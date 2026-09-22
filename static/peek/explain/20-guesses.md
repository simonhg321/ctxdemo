# guesses
The model does not know its answer. At every step it holds a **ranked list of guesses** for the next piece, picks one, adds it to the sentence, and starts over. The answer you read is a chain of a few hundred of those picks.

The colour of each piece is how sure it was when it picked it:

- **green** — 90% or more. Almost no contest.
- **amber** — between 50% and 90%. It had a real runner-up.
- **red** — under 50%. A coin-flip; the runner-up was as likely as the pick.

The rings mark the three least-sure pieces of the answer, with what it nearly said instead. Tap any piece to see its whole list.

Watch for this: a **wrong** answer can be all green. Colour measures how *familiar* the pattern is, not whether it is true.
