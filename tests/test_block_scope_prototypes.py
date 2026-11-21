"""Rewrites the permuter generator must not make: a block-scope prototype is not a local built by its constructor
(decompdecomp #301/#304), and a definition with an attribute in front of it is still found."""
import re

from decomprepair import csource
from decomprepair.permuter_gen import Restorer


def test_a_block_scope_prototype_isnt_a_local_built_by_its_constructor():
    """A prototype in a body has the shape of a local built by its constructor, and pycparser refused the rewritten
    `T t = DDctor(...)`: 2,495 log lines and 276 of 287 on a GameCube project. `extern`, a `void` return, or a
    parameter list (not expressions) tells the two apart; `T t(x)` with `x` a variable is still one."""


    source = ("void use(void **p, s32 n)\n{\n"
              "    extern s32 __OSUnlockSramEx(s32);\n"
              "    void fn_8011176C(void **, void *, void *);\n"
              "    extern s32 OSDisableInterrupts(void);\n"
              "    extern void fn_802325CC(const char *, s32, const char *, ...);\n"
              "    s32 Maybe(s32);\n"
              "    Vec v(1.0f, n);\n"
              "    Foo f(a, &b);\n"
              "    Widget w(k);\n"
              "    Vec2 d(Vec2(1.0f, 2.0f));\n"
              "}\n")
    r = Restorer(source, {"s32", "Vec", "Foo", "Widget", "Vec2"})
    assert "extern s32 __OSUnlockSramEx(s32);" in r.source
    assert "void fn_8011176C(void **, void *, void *);" in r.source
    assert "extern s32 OSDisableInterrupts(void);" in r.source
    assert "extern void fn_802325CC(const char *, s32, const char *, ...);" in r.source
    assert "s32 Maybe(s32);" in r.source  # (no `extern` and not `void`: the parameter list says it)
    assert not re.search(r"\b(?:__OSUnlockSramEx|fn_8011176C|OSDisableInterrupts|fn_802325CC|Maybe)\s*=", r.source)
    assert "Vec v = DDctor(1.0f, n);" in r.source and "Foo f = DDctor(a, &b);" in r.source
    assert "Widget w = DDctor(k);" in r.source  # (k is a variable, not a type)
    # a temporary is one of a constructor's arguments, not a parameter: pycparser reads the constructor call after all
    assert "Vec2 d = DDctor(DDnew_Vec2(1.0f, 2.0f));" in r.source
    assert r.restore(r.source) == source


def test_find_reads_a_definition_with_an_attribute_in_front():
    """`__attribute__((...))` and MSVC's `__declspec(...)` hold parentheses but aren't expressions: the definition
    after them is found, so the function gets its local hypotheses."""
    for head in ("static inline __attribute__((always_inline)) void", "__declspec(noinline) void",
                 "static __attribute__((section(\".text\"))) void"):
        text = f"int x;\n{head} f(int a)\n{{\n    g(a);\n}}\n"
        span = csource.find(text, "f")
        assert span is not None and text[span[0]:span[1]].rstrip().endswith("}")
    assert csource.find("void g(void)\n{\n    x = (f(1));\n}\n", "f") is None
