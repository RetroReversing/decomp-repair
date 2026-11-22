from decomprepair.measured_saved_global import variants

SOURCE = '''typedef int M2C_UNK;
s32 example(void) {
    M2C_UNK *old;
    M2C_FIELD(&base, M2C_UNK **, 0x20) = &replacement;
    saved = old;
    old = M2C_FIELD(&base, M2C_UNK **, 0x20);
    return 0;
}
'''
TARGET = ['lui $v1, %hi(slot)', 'lw $v1, %lo(slot)($v1)', 'lui $at, %hi(slot)',
          'sw $v0, %lo(slot)($at)', 'lui $at, %hi(saved)', 'sw $v1, %lo(saved)($at)']
CANDIDATE = TARGET[2:]
ROWS = [('r', TARGET[i], CANDIDATE[i - 2] if i >= 2 else '') for i in range(len(TARGET))]


def resolve(name):
    return {'base': 0x1000, 'slot': 0x1020}.get(name)


def test_recovers_previous_pointer_at_verified_alias():
    result = variants(SOURCE, 'example', '', ROWS, resolve=resolve)
    assert len(result) == 1
    assert 'extern M2C_UNK *slot;' in result[0][1]
    assert 'old = slot;\n    slot = &replacement;\n    saved = old;' in result[0][1]


def test_requires_alias_and_evidence_without_extra_uses():
    assert not variants(SOURCE, 'example', '', ROWS)
    assert not variants(SOURCE, 'example', '', ROWS, resolve=lambda _: 0)
    assert not variants(SOURCE, 'example', 'extern int slot;', ROWS, resolve=resolve)
    assert not variants(SOURCE.replace('return 0;', 'use(old); return 0;'), 'example', '', ROWS, resolve=resolve)
    assert not variants(SOURCE, 'example', '', [('r', t, t) for t in TARGET], resolve=resolve)
