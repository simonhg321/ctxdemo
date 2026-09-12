"""The map: a concept graph of what the conversation is holding. Pure data — no model calls here.

Nodes are concepts (short nouns) the model extracts from each exchange. Edges are co-mentions.
`survive(text)` is the compaction/handoff rule: a node lives on only if the summary/note still says it.
`generation` counts how many times a node has survived on paper only (a copy of a copy)."""
from __future__ import annotations
import copy, json, re
from dataclasses import dataclass

EXTRACT_PROMPT = ("Read this exchange and list the 3 to 6 most important concepts as short nouns (1-3 words, lower-case). "
                  "Then list pairs of those concepts that are directly related. "
                  'Reply with JSON only: {"concepts": ["..."], "links": [["a", "b"]]}\n\n')
_NOISE = re.compile(r"[^a-z0-9' \-]+")
PREFIX = 5


def norm_label(s: str) -> str:
    s = re.sub(r"\s+", " ", _NOISE.sub(" ", (s or "").lower())).strip()
    if " " not in s and len(s) > 3 and s.endswith("s") and not s.endswith("ss"):   # gpus -> gpu; bus stays; phrases untouched
        s = s[:-1]
    return s


def parse_extract(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Tolerant: strips fences/chatter, takes the first {...} block. Never raises."""
    if not text:
        return [], []
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], []
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [], []
    concepts = j.get("concepts") if isinstance(j, dict) else None
    if not isinstance(concepts, list):
        return [], []
    concepts = [c for c in concepts if isinstance(c, str) and c.strip()]
    raw_links = j.get("links")
    links = []
    for l in raw_links if isinstance(raw_links, list) else []:
        if isinstance(l, (list, tuple)) and len(l) == 2 and all(isinstance(x, str) for x in l):
            links.append((l[0], l[1]))
    return concepts, links


@dataclass
class Node:
    label: str
    first_n: int
    mentions: int = 1
    generation: int = 0      # 0 = said in this transcript; +1 per survive without being re-mentioned
    fresh: bool = True       # mentioned since the last survive


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str], int] = {}

    def _edge(self, a: str, b: str, w: int = 1) -> tuple[str, str] | None:
        if a == b or a not in self.nodes or b not in self.nodes:
            return None
        k = (a, b) if a < b else (b, a)
        self.edges[k] = self.edges.get(k, 0) + w
        return k

    def apply(self, n: int, concepts: list[str], links: list[tuple[str, str]]) -> dict:
        added, bumped, touched = [], [], []
        seen: list[str] = []
        for c in concepts:
            k = norm_label(c)
            if not k or k in seen:
                continue
            seen.append(k)
            if k in self.nodes:
                nd = self.nodes[k]; nd.mentions += 1; nd.generation = 0; nd.fresh = True; bumped.append(k)
            else:
                self.nodes[k] = Node(k, n); added.append(k)
        for i, a in enumerate(seen):
            for b in seen[i + 1:]:
                e = self._edge(a, b)
                if e and e not in touched:
                    touched.append(e)
        for a, b in links:
            e = self._edge(norm_label(a), norm_label(b))
            if e and e not in touched:
                touched.append(e)
        return {"added": added, "bumped": bumped, "edges": [[a, b, self.edges[(a, b)]] for a, b in sorted(touched)]}

    def _mentioned(self, label: str, text: str) -> bool:
        return label in text or (len(label) >= PREFIX and label[:PREFIX] in text)

    def survive(self, text: str) -> dict:
        """Compaction / handoff. Keeps nodes the text still mentions; the rest are absorbed into their heaviest surviving neighbour."""
        t = (text or "").lower()
        keep = [k for k in self.nodes if self._mentioned(k, t)]
        kept, absorbed = [], []
        for k in keep:
            nd = self.nodes[k]
            nd.generation = 1 if nd.fresh else nd.generation + 1
            nd.fresh = False
            kept.append([k, nd.generation])
        heaviest = max(keep, key=lambda k: (self.nodes[k].mentions, -keep.index(k)), default=None)
        for k in list(self.nodes):
            if k in keep:
                continue
            best, bw = None, 0
            for (a, b), w in self.edges.items():
                other = b if a == k else a if b == k else None
                if other in keep and (w > bw or (w == bw and best is not None and other < best)):
                    best, bw = other, w
            absorbed.append([k, best or heaviest])
            del self.nodes[k]
        self.edges = {e: w for e, w in self.edges.items() if e[0] in self.nodes and e[1] in self.nodes}
        return {"kept": kept, "absorbed": absorbed}

    def survivors_copy(self, text: str) -> "Graph":
        g = copy.deepcopy(self)
        g.survive(text)
        return g

    def to_dict(self) -> dict:
        return {"nodes": [{"label": nd.label, "first_n": nd.first_n, "mentions": nd.mentions, "generation": nd.generation}
                          for nd in self.nodes.values()],
                "edges": [[a, b, w] for (a, b), w in self.edges.items()]}
