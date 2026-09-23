# inside the head
The model is a stack of **layers** — 36 of them in the sibling this wall reads. Each layer takes the running guess about the next piece and rewrites it a little. Read the guess out after every layer and you can watch an answer form: nothing, then a vague word, then the right word getting surer, then locked in.

- **the column** — one chip per layer, bottom to top. The chip shows that layer's best guess and how sure it was. Chips turn the answer's colour once they agree with the final word.
- **decided here** — the first layer after which the guess never changes again. Early = the model "knew"; late = it was still arguing with itself.
- **where it looked** — which pieces of the question the model paid attention to when it decided. The first piece is skipped: models park spare attention there.

Tap any piece of the answer and the column shows how *that* piece formed. Red pieces are decided late.

Honesty note: the layers you see belong to a **4B sibling** of the model that answered — same family, same design, smaller. When the two disagree the panel says so; that disagreement is a lesson too.
