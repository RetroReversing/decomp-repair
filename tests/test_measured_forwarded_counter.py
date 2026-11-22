from decomprepair import measured_forwarded_counter as repair

SOURCE = '''
M2C_UNK select(s32, void *); /* extern */
s32 f(void) {
    u16 current;
    u16 next;
    current = read_count();
    next = current + 1;
    if (current < 5) {
        save(next);
        select(next, table);
    }
    return 0;
}
'''
ROWS = [
    ('i', 'beqz $v0, 80', 'beqz $v0, 84'),
    ('o', 'addiu $a1, $a1, 1', 'sltiu $v0, $v1, 2'),
    (' ', 'jal select', 'jal select'),
    ('r', 'addiu $a1, $a1, -1', 'addiu $a0, $a0, -1'),
]


def test_sink_increment_and_compose_forwarded_argument(monkeypatch):
    monkeypatch.setattr(repair, '_missing_caller_argument', lambda src, name, header, asm, callee: src + '\n/* forwarded */')
    result = dict(repair.variants(SOURCE, 'f', '', ROWS, ''))
    assert set(result) == {'guarded_counter_increment', 'forwarded_guard_counter'}
    assert result['guarded_counter_increment'].index('if (current < 5)') < result['guarded_counter_increment'].index('next = current + 1;')
    assert result['forwarded_guard_counter'].endswith('/* forwarded */')
    assert set(dict(repair.variants(SOURCE, 'f', 's32 f(void);', ROWS, ''))) == {'guarded_counter_increment'}


def test_decline_escaped_locals_and_effectful_conditions(monkeypatch):
    monkeypatch.setattr(repair, '_missing_caller_argument', lambda *args: 'forwarded')
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('u16 next;', 'volatile u16 next;'), '', ROWS),
        (SOURCE.replace('if (current < 5)', 'if (current++ < 5)'), '', ROWS),
        (SOURCE.replace('if (current < 5)', 'if ((current = 3) < 5)'), '', ROWS),
        (SOURCE.replace('if (current < 5)', 'if (use(&current))'), '', ROWS),
        (SOURCE.replace('return 0;', 'use(next); return 0;'), '', ROWS),
        (SOURCE, '#define ALIAS next', ROWS),
        (SOURCE, 'typedef volatile int u16;', ROWS),
    ]:
        assert repair.variants(source, 'f', header, rows, '') == []
