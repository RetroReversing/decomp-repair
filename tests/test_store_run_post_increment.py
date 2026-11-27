"""Stores at consecutive indexes, with the first ones stepping the pointer."""
from decomprepair import store_run_post_increment as run

SOURCE = '''void f(u8 *name) {
    u8 *p;

    p = name;
    while (*p != 0) {
        p++;
    }
    p[0] = 'P';
    p[1] = 'A';
    p[2] = 'K';
    open(name);
}
'''


def test_the_first_store_and_every_store_but_the_last():
    first, every = [text for _, text in run.variants(SOURCE, 'f')]
    assert "    *p++ = 'P';\n    p[0] = 'A';\n    p[1] = 'K';\n" in first
    assert "    *p++ = 'P';\n    *p++ = 'A';\n    p[0] = 'K';\n" in every


def test_a_pointer_used_afterwards_or_in_a_loop_is_left_alone():
    assert run.variants(SOURCE.replace('open(name);', 'open(p);'), 'f') == []
    looped = SOURCE.replace("    p[0] = 'P';", "    while (more()) {\n    p[0] = 'P';").replace(
        '    open(name);', '    }\n    open(name);')
    assert run.variants(looped, 'f') == []
