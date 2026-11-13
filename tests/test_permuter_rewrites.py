"""The permuter's rewrites: they propose C only; nothing here compiles or judges."""
import random
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
