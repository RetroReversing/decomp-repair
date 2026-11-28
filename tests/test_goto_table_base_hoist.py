"""Only an unescaped, invariant table address is moved out of a goto loop."""
import shutil
import subprocess

import pytest

from decomprepair.goto_table_base_hoist import FAMILY, variants

SOURCE = '''extern u8 table[];
int total;
void f(int n) {
    u8 *base;
    int i, x;
    i = 0;
    loop: {
        x = i;
        base = table;
        total += base[x];
        i++;
    }
    if (i < n) goto loop;
}
'''
HEADER = 'typedef unsigned char u8;'


def test_address_moves_before_label_and_reads_stay_in_loop():
    out = variants(SOURCE, 'f', HEADER)
    assert len(out) == 1 and out[0][0] == FAMILY
    child = out[0][1]
    assert child.index('base = table;') < child.index('loop:')
    assert child.count('base = table;') == 1 and 'total += base[x];' in child


@pytest.mark.parametrize('change', [
    lambda s: s.replace('base = table;', 'if (i) base = table;'),
    lambda s: s.replace('base = table;', 'if (i) {\n            base = table;\n        }'),
    lambda s: s.replace('x = i;', 'if (i) return; x = i;'),
    lambda s: s.replace('x = i;', 'touch(); x = i;'),
    lambda s: s.replace('x = i;', 'x = *base;'),
    lambda s: s.replace('total += base[x];', 'escape(&(base)); total += base[x];'),
    lambda s: s.replace('total += base[x];', '(base)++; total += base[x];'),
    lambda s: s.replace('total += base[x];', 'base = other; total += base[x];'),
    lambda s: s.replace('total += base[x];', 'inside: total += base[x];'),
    lambda s: s.replace('i = 0;', 'i = 0; save(&&loop);'),
    lambda s: s.replace('if (i < n) goto loop;', 'if (i < n) goto loop; goto loop;'),
    lambda s: s.replace('void f(int n)', 'void f(int n, char *table)'),
    lambda s: s.replace('x = i;', 'READ(x); x = i;'),
    lambda s: s.replace('base = table;', '__asm__("" : "=r"(base)); base = table;'),
])
def test_unsafe_shapes_are_not_hoisted(change):
    assert not variants(change(SOURCE), 'f', HEADER + '\n#define READ(x) (x)')


def test_unknown_preprocessor_input_is_rejected():
    assert not variants(SOURCE, 'f', HEADER + '\n#include_next "unknown.h"')
    assert not variants(SOURCE, 'f', HEADER, ['@flags.rsp'])


def test_original_and_hoisted_loop_agree(tmp_path):
    cc = shutil.which('cc')
    if cc is None:
        pytest.skip('a C compiler is required for the semantic control')
    child = variants(SOURCE, 'f', HEADER)[0][1]
    original = SOURCE.replace('total', 'old_total').replace('void f(', 'void old_f(')
    harness = '''u8 table[] = {1, 2, 3, 4};
int main(void) {
    int n;
    for (n = 0; n < 4; ++n) {
        total = old_total = 0; f(n); old_f(n);
        if (total != old_total) return 1;
    }
    return 0;
}'''
    path = tmp_path / 'control.c'
    path.write_text(HEADER + child + original + harness)
    binary = tmp_path / 'control'
    subprocess.run([cc, '-std=c89', '-Wall', '-Werror', str(path), '-o', str(binary)], check=True, timeout=30)
    subprocess.run([str(binary)], check=True, timeout=30)
