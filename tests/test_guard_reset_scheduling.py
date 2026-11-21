from decomprepair.guard_reset_scheduling import variants

SOURCE = '''
extern volatile s32 flag;
extern volatile s32 limit;
extern s32 x, y, a, b;
void f(void) {
    s32 index;
    do { { s32 first = a; s32 second = b; x = first; y = second; } flag = 0; index = 0; } while (0);
    if (limit > 0) {
        do { index++; } while ((s32)(u16)index < limit);
    }
}
'''
ROWS = [
    ('o', '', 'lui $at, %hi(flag)'),
    ('o', '', 'sw $zero, %lo(flag)($at)'),
    (' ', 'lui $v0, %hi(limit)', 'lui $v0, %hi(limit)'),
    (' ', 'lw $v0, %lo(limit)($v0)', 'lw $v0, %lo(limit)($v0)'),
    ('o', 'lui $at, %hi(flag)', ''),
    ('o', 'sw $zero, %lo(flag)($at)', ''),
    ('i', 'blez $v0, 0x48', 'blez $v0, 0x4c'),
]


def test_capture_only_initial_bound():
    [(family, source)] = variants(SOURCE, 'f', '', ROWS)
    assert family == 'guard_reset_scheduling'
    assert 'x = first; y = second; } while (0);' in source
    assert 's32 initial_bound = limit; flag = 0; index = 0;' in source
    assert 'if (initial_bound > 0)' in source
    assert 'while ((s32)(u16)index < limit);' in source


def test_requires_reversed_relocations_and_scoped_reads():
    assert not variants(SOURCE, 'f', '', ROWS[2:])
    assert not variants(SOURCE.replace('volatile s32 limit', 's32 limit'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('< limit', '< 5'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('if (limit', 's32 limit; if (limit'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('    }\n}', '    } else {}\n}'), 'f', '', ROWS)


def test_avoids_header_name_collision():
    [(_, source)] = variants(SOURCE, 'f', '#define initial_bound 5', ROWS)
    assert 's32 initial_bound_ = limit;' in source


def test_try_one_shot_counter_reset_when_target_uses_the_branch_delay_slot():
    rows = [('o', '', 'move $s1, $zero')] + ROWS + [('o', 'move $s1, $zero', 'andi $v0, $s1, 0xffff')]
    [(family, fast), (fallback, _)] = variants(SOURCE, 'f', '', rows)
    assert family == 'guard_reset_delay_slot'
    assert 'flag = 0; do { index = 0; } while (0);' in fast
    assert fallback == 'guard_reset_scheduling'
    assert len(variants(SOURCE, 'f', '', rows[1:])) == 1
