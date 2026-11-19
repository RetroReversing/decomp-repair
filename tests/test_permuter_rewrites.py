"""The permuter's rewrites: they propose C only; nothing here compiles or judges."""
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

import decomprepair
from decomprepair.permuter import mutate
from decomprepair.permuter_local import variants

SOURCE = 'int f(int a, int b) {\n    int x;\n    int y;\n    x = a + 1;\n    y = b + 2;\n    return x + y;\n}\n'


def test_simple_rewrites_change_the_function_and_repeat_for_a_seed():
    first = [mutate(SOURCE, random.Random(seed)) for seed in range(20)]
    assert any(v and v != SOURCE for v in first)
    assert first == [mutate(SOURCE, random.Random(seed)) for seed in range(20)]


def test_local_orderings_swap_adjacent_constant_stores_only():
    text = 'void other(void){return;}\nvoid f(Item *p) {\n  p->y = 0;\n  p->x = 0;\n}\n'
    assert variants(text, 'f') == [('adjacent_constant_stores',
                                    text.replace('  p->y = 0;\n  p->x = 0;', '  p->x = 0;\n  p->y = 0;'))]
    assert not variants('void f(Item *p) {\n  p->y = 0;\n  call();\n  p->x = 0;\n}', 'f')


def test_initialization_guard_rejects_a_new_uninitialized_read():
    from decomprepair.permuter_initialization import unsafe_temporary

    parent = 'int f(int a) {\n  int x;\n  x = a;\n  return x;\n}\n'
    assert not unsafe_temporary(parent, parent, 'f')


def test_line_groups_keep_the_original_layout():
    from decomprepair.permuter_formatting import LineGroups

    parser = pytest.importorskip('pycparser').CParser
    guard = LineGroups('int f(void) { int x; x=1; x|=8; return x; }', '', 'f', parser().parse)
    assert 'x = 1; x |= 8;' in guard.apply('int f(void) {\n  int x;\n  x = 1;\n  x |= 8;\n  return x;\n}\n')


def test_the_generator_is_a_program_beside_its_helpers():
    """Callers run permuter_gen.py by path, with decomp-permuter's Python: its helpers must be next to it, and it
    must not import the package (decomp-permuter's environment doesn't have it)."""
    folder = Path(decomprepair.__file__).parent
    for helper in ('permuter_gen.py', 'permuter_capture.py', 'permuter_dependencies.py', 'permuter_formatting.py'):
        assert (folder / helper).is_file()
        assert 'decomprepair' not in (folder / helper).read_text().split('"""', 2)[-1]
    run = subprocess.run([sys.executable, '-I', '-c', 'import ast,sys; ast.parse(open(sys.argv[1]).read())',
                          str(folder / 'permuter_gen.py')], capture_output=True)
    assert run.returncode == 0


def test_rewrites_name_only_declared_typedefs():
    # An N64 function's C with no zlib in sight: `(uInt)arg0` made nearly every rewrite fail to compile.
    source = 'int f(int a) {\n    int x;\n    x = a + 1;\n    return x;\n}\n'
    outs = {mutate(source, random.Random(seed)) for seed in range(400)}
    assert not any(t in (v or '') for v in outs for t in ('uInt', 'uLong', 's32', 'u32'))
    with_header = {mutate(source, random.Random(seed), header='typedef int s32;') for seed in range(400)}
    assert any('s32' in (v or '') for v in with_header) and not any('uInt' in (v or '') for v in with_header)


def test_register_is_never_added_to_an_assignment():
    """`D_80102ED4 = 0;` once read as type `D_80102ED` and name `4`: the toggle declared a new local in place of the
    global's store, and 35 functions of an N64 game kept that as their best C."""
    import random

    from decomprepair import permuter
    lines = ['void f(void) {', '    s32 v;', '', '    D_80102ED4 = 0;', '    v = g();', '    return v;', '}']
    for seed in range(200):
        out = permuter._toggle_register(list(lines), random.Random(seed))
        assert out is not None
        assert out[3] == '    D_80102ED4 = 0;' and out[4] == '    v = g();' and out[5] == '    return v;'
        assert out[1] in ('    s32 v;', '    register s32 v;')


def test_a_split_pointer_sum_adds_bytes_whatever_the_pointer_type():
    """`p = (char *)(i * 4); p += (s32)(D);` on an `s32 *` added D four times over; 8 functions of an N64 game kept
    that as their best C."""
    from decomprepair import value_repairs
    source = 'void f(u32 i) {\n    s32 *p;\n\n    p = (i * 4) + D;\n    *p = 1;\n}\n'
    texts = [t for _, t in value_repairs.variants(source, 'f')]
    split = [t for t in texts if 'p = (void *)((i * 4));' in t]
    assert split and 'p = (void *)((char *)p + (s32)(D));' in split[0]
    assert not any('p += (s32)' in t for t in texts)

def test_a_cast_never_cuts_a_pointer():
    """The operand of a pointer cast once became `(unsigned short)D_80109698`: an address cut to 16 bits."""
    from decomprepair import permuter
    lines = ['void f(void) {', '    s32 v;', '',
             '    (*(s32 *)((char *)(D_80109698) + 0xFC)) = v;', '    temp = (void *) p;', '    v = w + 1;', '}']
    seen = set()
    for seed in range(300):
        out = permuter._add_cast(list(lines), random.Random(seed))
        assert out is not None
        assert '((char *)(D_80109698) +' in out[3] and out[4] == lines[4]
        seen.add(out[5])
    assert any(line != lines[5] for line in seen)

def test_a_cast_never_lands_on_a_literal():
    """`(unsigned short)0xDA380003` truncated a display-list command to 3; only hex literals slipped past `isdigit`."""
    import random

    from decomprepair import permuter
    lines = ['void f(void) {', '    s32 v;', '', '    v = 0xDA380003;', '    w = 12 + v;', '}']
    for seed in range(300):
        out = permuter._add_cast(list(lines), random.Random(seed))
        assert out is not None
        assert not re.search(r'\)\s*(?:0[xX][0-9A-Fa-f]+|\d+)\b', out[3] + out[4]), out


def test_a_random_cast_never_narrows_a_value():
    """`(unsigned short)flags | 1` stored only the low half of a word the game ORed whole."""
    import random as _random

    from decomprepair import permuter
    lines = ['void f(s32 *p) {', '    s32 v;', '', '    v = p[0];', '    p[1] = v | 1;', '}']
    for seed in range(300):
        out = permuter._add_cast(list(lines), _random.Random(seed))
        if out:
            assert '(short)' not in ''.join(out) and '(unsigned short)' not in ''.join(out)
