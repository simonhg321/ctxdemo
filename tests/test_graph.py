from app.graph import parse_extract, norm_label, Graph


def test_parse_clean_fenced_and_garbage():
    assert parse_extract('{"concepts": ["Quantization", "int8"], "links": [["quantization", "int8"]]}') == (["Quantization", "int8"], [("quantization", "int8")])
    assert parse_extract('```json\n{"concepts": ["a"], "links": []}\n```') == (["a"], [])
    assert parse_extract("Sure! Here you go: {\"concepts\": [\"gpu\"], \"links\": [[\"gpu\", 3]]} thanks") == (["gpu"], [])
    assert parse_extract("no json here") == ([], [])
    assert parse_extract('{"concepts": "not a list"}') == ([], [])


def test_norm_label():
    assert norm_label("  Quantization! ") == "quantization"
    assert norm_label("GPUs") == "gpu"
    assert norm_label("bus") == "bus"            # short words keep their s
    assert norm_label("Mixture   of Experts") == "mixture of experts"


def test_apply_adds_bumps_and_links_pairwise():
    g = Graph()
    d = g.apply(1, ["Quantization", "int8", "VRAM"], [("int8", "vram")])
    assert d == {"added": ["quantization", "int8", "vram"], "bumped": [],
                 "edges": [["int8", "quantization", 1], ["int8", "vram", 2], ["quantization", "vram", 1]]}
    d2 = g.apply(2, ["int8", "latency"], [])
    assert d2["added"] == ["latency"] and d2["bumped"] == ["int8"]
    assert g.nodes["int8"].mentions == 2 and g.nodes["int8"].first_n == 1 and g.nodes["latency"].first_n == 2
    assert g.edges[("int8", "latency")] == 1 and g.edges[("int8", "vram")] == 2
    assert g.apply(3, ["int8", "int8"], [("int8", "int8")])["edges"] == []      # no self edges, no dup


def test_survive_keeps_mentioned_absorbs_rest_and_counts_generations():
    g = Graph()
    g.apply(1, ["quantization", "int8", "vram"], [])
    g.apply(2, ["vram", "gpu"], [])
    d = g.survive("We talked about quantization and the GPU.")
    assert d["kept"] == [["quantization", 1], ["gpu", 1]]
    # int8's surviving neighbour: quantization (w1). vram: quantization (w1) and gpu (w1) tie -> alphabetical -> gpu
    assert d["absorbed"] == [["int8", "quantization"], ["vram", "gpu"]]
    assert set(g.nodes) == {"quantization", "gpu"}
    g.apply(3, ["quantization"], [])
    assert g.nodes["quantization"].generation == 0
    d2 = g.survive("quantization and gpu again")
    assert d2["kept"] == [["quantization", 1], ["gpu", 2]]


def test_survive_prefix_match_and_nothing_survives():
    g = Graph()
    g.apply(1, ["mixture of experts", "routing"], [])
    d = g.survive("mixtures were discussed")            # 5+ char prefix 'mixtu' matches
    assert d["kept"] == [["mixture of experts", 1]] and d["absorbed"] == [["routing", "mixture of experts"]]
    g2 = Graph(); g2.apply(1, ["a-thing", "b-thing"], [])
    d = g2.survive("nothing relevant")
    assert d == {"kept": [], "absorbed": [["a-thing", None], ["b-thing", None]]} and g2.nodes == {}


def test_survivors_copy_leaves_original_alone():
    g = Graph(); g.apply(1, ["alpha", "beta"], [])
    c = g.survivors_copy("alpha only")
    assert set(c.nodes) == {"alpha"} and set(g.nodes) == {"alpha", "beta"}
    assert c.nodes["alpha"].generation == 1 and g.nodes["alpha"].generation == 0


def test_to_dict_shape():
    g = Graph(); g.apply(1, ["alpha", "beta"], [])
    d = g.to_dict()
    assert d["nodes"] == [{"label": "alpha", "first_n": 1, "mentions": 1, "generation": 0},
                          {"label": "beta", "first_n": 1, "mentions": 1, "generation": 0}]
    assert d["edges"] == [["alpha", "beta", 1]]
