from decomprepair.measured_conditional_flag_owner import variants

SOURCE = '''void update(void *arg, s32 enabled) {
    s16 flags;
    if (enabled != 0) {
        flags = M2C_FIELD(M2C_FIELD(&base, void **, 0x20), u16 *, 0x20) | 0x40;
        goto done;
    }
    if (M2C_FIELD(M2C_FIELD(&base, void **, 0x20), u16 *, 0x20) & 0x40) {
        M2C_FIELD(arg, u16 *, 0x68) = 2;
        flags = M2C_FIELD(M2C_FIELD(&base, void **, 0x20), u16 *, 0x20) & 0xffbf;
done:
        M2C_FIELD(M2C_FIELD(&base, void **, 0x20), s16 *, 0x20) = flags;
    }
}
'''
LOAD = ['lui $v1, %hi(owner)', 'lw $v1, %lo(owner)($v1)', 'lhu $v0, 0x20($v1)']
T = LOAD + ['nop'] + LOAD + ['andi $v0, $v0, 0xffbf', 'sh $v0, 0x20($v1)']
C = ['andi $v1, $v0, 0xffbf', 'lui $v0, %hi(owner)', 'lw $v0, %lo(owner)($v0)', 'sh $v1, 0x20($v0)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(max(len(T), len(C)))]


def resolve(name):
    return {'base': 0x1000, 'owner': 0x1020}.get(name)


def test_retains_branch_owner_for_shared_flag_store():
    result = variants(SOURCE, 'update', '', ROWS, resolve=resolve)
    assert len(result) == 1
    assert result[0][1].count('__repair_flag_owner = M2C_FIELD(&base, void **, 0x20);') == 2
    assert 'M2C_FIELD(__repair_flag_owner, s16 *, 0x20) = flags;' in result[0][1]


def test_requires_matching_alias_and_nonvolatile_source():
    assert not variants(SOURCE, 'update', '', ROWS)
    assert not variants(SOURCE, 'update', '', ROWS, resolve=lambda _: 0)
    assert not variants(SOURCE.replace('s16 flags;', 'volatile s16 flags;'), 'update', '', ROWS, resolve=resolve)
    assert not variants(SOURCE.replace('goto done;', 'return;'), 'update', '', ROWS, resolve=resolve)
