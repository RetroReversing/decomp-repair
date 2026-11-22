"""statement_group_orders: every dependency-respecting order of a small statement group, one child each."""
import itertools

from decomprepair import statement_group_orders as g

RUN = ["    scale = 0.015625f;\n", "    flags = (s8) arg4;\n", "    next = cur + 1;\n"]


def source(order):
    return ("void walk(s32 *cur, s32 arg4)\n{\n  f32 scale;\n  s8 flags;\n  s32 *next;\n"
            + ''.join(RUN[i] for i in order)
            + "  do\n  {\n    *next = (s32) (flags * scale);\n    next++;\n  } while (*cur);\n}\n")


def test_the_target_order_is_one_child_from_every_other_order():
    # a spilled-parameter function: five orders scored 60, one 0, and a swap of two from most of them is another 60
    target = source((0, 1, 2))
    for order in itertools.permutations(range(3)):
        if order == (0, 1, 2):
            continue
        children = [child for family, child in g.variants(source(order), 'walk')]
        assert target in children
        assert len(children) == 5  # the other five orders; a pair window's swap is one of them


def test_dependent_statements_keep_their_order():
    text = "void f(s32 a)\n{\n  s32 x;\n  s32 y;\n  x = a + 1;\n  y = x * 2;\n  g_out = y;\n}\n"
    assert g.variants(text, 'f') == []


def test_memory_accesses_are_not_reordered_past_a_store_but_loads_are():
    text = ("void f(s32 *p)\n{\n  s32 x;\n  s32 y;\n  s32 z;\n  x = p[0];\n  y = p[1];\n  p[2] = 0;\n  z = 3;\n}\n")
    children = [child for _, child in g.variants(text, 'f')]
    assert any("  y = p[1];\n  x = p[0];\n" in c for c in children)
    assert not any(c.index('p[2] = 0') < c.index('y = p[1]') for c in children)
    assert any(c.index('z = 3') < c.index('p[2] = 0') for c in children)


def test_calls_and_volatile_are_left_alone():
    text = "void f(void)\n{\n  s32 x;\n  s32 y;\n  x = g();\n  y = 2;\n}\n"
    assert g.variants(text, 'f') == []
