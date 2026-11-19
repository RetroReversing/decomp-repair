"""m2c's per-element stack locals, one array whose first element's address escapes, as that array again."""
from decomprepair import stack_run_array_repairs as r

SOURCE = '''void f(f32 *a, f32 w) {
    f32 sp18;
    f32 sp1C;
    s32 sp20;
    f32 sp40;

    sp18 = a[0] * w;
    sp1C = a[1] * w;
    sp20 = 0;
    sp40 = w;
    g(&sp18, sp40);
}
'''


def test_the_run_becomes_one_array():
    # An N64 function kept 112 of the game's 183 instructions: only &sp18 escaped, so the other elements' stores
    # were dead and gcc deleted their arithmetic. As one array: 47.3% -> 94.2%.
    (family, out), = r.variants(SOURCE, 'f')
    assert family == 'stack_run_array'
    assert '    f32 sp18[3];\n' in out and 'f32 sp1C;' not in out and 's32 sp20;' not in out
    assert 'sp18[0] = a[0] * w;' in out and 'sp18[1] = a[1] * w;' in out and 'sp18[2] = 0;' in out
    assert 'g(sp18, sp40);' in out or 'g(&sp18[0], sp40);' in out or 'g(&sp18, sp40);' not in out
    assert 'f32 sp40;' in out  # not contiguous with the run


def test_left_alone_without_an_escaping_address_or_a_run():
    assert r.variants(SOURCE.replace('g(&sp18, sp40);', 'g(sp18, sp40);'), 'f') == []
    assert r.variants(SOURCE.replace('    f32 sp1C;\n', '').replace('    s32 sp20;\n', '')
                      .replace('    sp1C = a[1] * w;\n', '').replace('    sp20 = 0;\n', ''), 'f') == []
    # an address taken inside the run starts a run of its own: sp18 stays a single local
    (_, split), = r.variants(SOURCE.replace('g(&sp18, sp40);', 'g(&sp18, sp40);\n    g(&sp1C, sp40);'), 'f')
    assert '    f32 sp18;\n' in split and '    f32 sp1C[2];\n' in split


def test_propose_finds_it():
    from decomprepair.propose import propose
    assert any(p.module == 'stack_run_array_repairs' for p in propose(SOURCE, 'f').proposals)


def test_a_run_the_target_keeps_in_memory_counts_without_an_address():
    # Three blend weights at sp40..sp48 the game stores and reloads at their slots; m2c's C never takes an address.
    source = SOURCE.replace('    f32 sp40;\n', '    f32 sp40;\n    f32 sp44;\n    f32 sp48;\n').replace(
        '    sp40 = w;\n', '    sp40 = w;\n    sp44 = w;\n    sp48 = w;\n')
    asm = 'swc1 $f0, 0x40($sp)\nswc1 $f2, 0x44($sp)\nlwc1 $f4, 0x48($sp)\n'
    outs = [t for _, t in r.variants(source, 'f', asm)]
    assert any('    f32 sp40[3];\n' in t and 'sp40[2] = w;' in t for t in outs)
    assert not any('f32 sp40[3];' in t for _, t in r.variants(source, 'f'))  # no evidence without the asm
