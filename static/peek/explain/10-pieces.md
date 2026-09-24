# pieces
The model never sees letters or words. Your sentence is chopped into **pieces** (the real word is *tokens*) — common words are one piece, rare words are several, and a space belongs to the word after it. "unbelievable" is three pieces (`un` + `belie` + `vable`); "strawberry" is just one.

That is why it cannot count the r's in strawberry: it has never seen the letters, only the one piece.

The **chunks** box shows your sentence exactly as it was chopped. The count under it is the honest one: pieces cost memory, and the backpack fills by pieces, not by words.
