from layers.lens import decided_at, heat, cut_front


def test_decided_at_is_the_first_layer_of_the_stable_suffix():
    assert decided_at(["the", "a", "Paris", "Paris", "Paris"]) == 3        # layers are 1-based on the wall
    assert decided_at(["Paris", "Paris"]) == 1
    assert decided_at(["a", "b", "Paris"]) == 3                              # decided at the very last layer
    assert decided_at(["Paris", "b", "Paris"]) == 3                          # an early agreement that flips does not count
    assert decided_at([]) is None


def test_heat_drops_the_sink_and_scales_to_one():
    assert heat([0.9, 0.05, 0.05]) == [0.0, 1.0, 1.0]
    assert heat([0.9, 0.05, 0.05], drop_first=False) == [1.0, 0.05 / 0.9, 0.05 / 0.9]
    assert heat([1.0]) == [0.0]                                              # a one-token prompt: nothing to look at
    assert heat([]) == []


def test_cut_front_keeps_the_end():
    assert cut_front([1, 2, 3, 4, 5], 3) == [3, 4, 5]
    assert cut_front([1, 2], 3) == [1, 2]
