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


HEAD = """extern void *gCursor;
extern s16 gW;
extern s16 gH;
extern s32 gFlag;
extern s32 gMode;
typedef struct { int w0; int w1; int w2; int w3; int w4; int w5; int w6; int w7; } Cmds;
void draw(void)
{
    s32 a;
    s32 b;
    s32 size;
    void *p;
    p = gCursor;
    gCursor = p + 8;
    ((Cmds *) p)->w0 = 0xE7000000;
    gCursor = p + 0x10;
    ((Cmds *) p)->w3 = 0x300000;
"""
TAIL = """    if (gFlag != 0) {
        size = (-(gMode == 0) & 3) | 2;
    }
    ((Cmds *) p)->w6 = (size << 19) | (a & 0xFFF);
}
"""
BEFORE = HEAD + """    gCursor = p + 0x18;
    ((Cmds *) p)->w2 = 0xE3000A01;
    ((Cmds *) p)->w1 = 0;
    ((Cmds *) p)->w4 = 0xE200001C;
    size = 2;
    ((Cmds *) p)->w5 = 0x0F0A4000;
    a = gW - 1;
    b = gH - 1;
""" + TAIL
SUNK = BEFORE.replace("    gCursor = p + 0x18;\n    ((Cmds *) p)->w2 = 0xE3000A01;\n",
                      "    ((Cmds *) p)->w2 = 0xE3000A01;\n    gCursor = p + 0x18;\n")
BOTH = SUNK.replace("    size = 2;\n", "").replace("    b = gH - 1;\n", "    b = gH - 1;\n    size = 2;\n")


def test_a_cursor_advance_sinks_past_the_stores_it_does_not_alias():
    # the advance and a store through the pointer it advances touch different memory
    assert SUNK in [c for _, c in g.variants(BEFORE, 'draw')]


def test_two_moves_that_tie_alone_are_one_child():
    # a display list built by KMC gcc 2.7.2, 4900 -> 0: the third advance one store down and `size = 2` past the
    # last loads scored 270 each alone and 0 together
    assert BOTH in [c for _, c in g.variants(BEFORE, 'draw')]


def test_an_advance_does_not_pass_a_read_of_its_own_global():
    text = ("extern void *gCursor;\nextern s32 gOut;\nvoid f(void)\n{\n  void *p;\n  s32 x;\n  p = gCursor;\n"
            "  gCursor = p + 8;\n  x = *(s32 *) gCursor;\n  gOut = x;\n}\n")
    assert all(c.index('gCursor = p + 8') < c.index('x = *(s32 *) gCursor') for _, c in g.variants(text, 'f'))
