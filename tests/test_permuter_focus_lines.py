"""Line focus for the permuter's randomizer: pure helpers and a stand-in for decomp-permuter's region picker."""
import random
from types import SimpleNamespace

from decomprepair import permuter_focus_lines as focus_lines

ORIGINAL = '/* note */\n#define X 1\nint f(int a) {\n    int c;\n    c = a * 3; // scale\n    return c;\n}\n'
FINAL = ' \nint f(int a) {\n    int c;\n    c = a * 3;\n    return c;\n}\n'


class Node:
    def __init__(self, kind, line, *children):
        self.kind, self.coord, self._children = kind, SimpleNamespace(line=line) if line else None, children

    def children(self):
        return [('c', child) for child in self._children]


Node.__name__ = 'Node'


def named(kind):
    return type(kind, (Node,), {})


def tree():
    Assign, If, Compound, FuncDef = named('Assignment'), named('If'), named('Compound'), named('FuncDef')
    first = Assign(None, 5, Node('x', 5))
    second = Assign(None, 6, Node('x', 6))
    third = Assign(None, 7, Node('x', 7))
    top = FuncDef(None, 4, Compound(None, 4, first, If(None, 6, second), third))
    indices = SimpleNamespace(starts={}, ends={})
    for number, node in enumerate([first, second, third], 1):
        indices.starts[node], indices.ends[node] = number * 10, number * 10 + 5
        for _, child in node.children():
            indices.starts[child], indices.ends[child] = number * 10 + 1, number * 10 + 2
    return top, indices, (first, second, third)


def test_lines_are_followed_through_comments_directives_and_blank_lines():
    assert focus_lines.line_map(ORIGINAL, FINAL) == {3: 2, 4: 3, 5: 4, 6: 5, 7: 6}
    assert focus_lines.lines_in_unit([5, 2, 99, 'x'], ORIGINAL, FINAL, 100) == {104}  # (line 2 was a directive)


def test_spans_cover_the_statements_that_begin_on_a_line_and_skip_blocks():
    top, indices, (first, second, third) = tree()
    assert focus_lines.line_spans(top, indices, {5, 6}) == {5: (10, 15), 6: (20, 25)}
    assert focus_lines.line_spans(top, indices, {4}) == {}  # a Compound or FuncDef is not a place to rewrite


class Region:
    def __init__(self, start, end, indices):
        self.start, self.end, self.indices = start, end, indices

    def is_unbounded(self):
        return self.indices is None


def test_the_region_wraps_a_focus_line_and_its_neighbours_only_a_share_of_the_time():
    top, indices, _ = tree()
    focus = focus_lines.Focus({6}, share=1.0)
    region = focus.region(top, indices, random.Random(1), Region)
    assert (region.start, region.end) == (9, 36)  # lines 5..7: first start 10 .. last end 35, one either side
    assert focus_lines.Focus({6}, share=0.0).region(top, indices, random.Random(1), Region) is None
    assert focus_lines.Focus(set()).region(top, indices, random.Random(1), Region) is None
    assert focus_lines.Focus({99}, share=1.0).region(top, indices, random.Random(1), Region) is None


def test_install_keeps_a_sources_own_region_and_falls_back_to_the_whole_function():
    top, indices, _ = tree()
    marked = Region(1, 2, indices)
    module = SimpleNamespace(get_randomization_region=lambda *args: marked)
    focus_lines.install(module, focus_lines.Focus({6}, share=1.0))
    assert module.get_randomization_region(top, indices, random.Random(0)) is marked
    whole = Region(-1, 99, None)
    module = SimpleNamespace(get_randomization_region=lambda *args: whole)
    focus = focus_lines.Focus(set(), share=1.0)
    focus_lines.install(module, focus)
    focus_lines.install(module, focus)  # (twice is once)
    assert module.get_randomization_region(top, indices, random.Random(0)) is whole
    focus.lines = {6}
    assert module.get_randomization_region(top, indices, random.Random(0)) is not whole
