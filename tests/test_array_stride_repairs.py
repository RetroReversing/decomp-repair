from decomprepair import array_stride_repairs as repair


def assembly(*lines):
    return '\n'.join(f'/* {i*4:X} {0x80000000+i*4:08X} 00000000 */  {line}'
                     for i, line in enumerate(lines))


def test_non_power_of_two_stride_and_signed_field():
    asm = assembly('sll     $t0, $a1, 1', 'addu $t0, $t0, $a1',
                   'sll $t0, $t0, 2', 'addu $t0, $a0, $t0',
                   'lh $v0, 4($t0)', 'jr $ra', 'nop')
    found = repair.evidence(asm)
    assert found == {(0, 1): {(12, 4): {'short'}}}
    source = 'int f(char *p, int i) { return M2C_FIELD(p + (i * 16), short *, 4); }'
    [(family, candidate)] = repair.variants(source, 'f', '', found)
    assert family == repair.FAMILY
    assert 'sizeof(__repair_array_record) == 12' in candidate
    assert '[i].field_4' in candidate
    assert not repair.variants(source.replace('short', 'unsigned short'), 'f', '', found)
    assert not repair.variants(source.replace('return', 'i++; return'), 'f', '', found)
    assert not repair.variants(source, 'f', '', {(0, 1): {(12, 4): {'short'}, (16, 4): {'short'}}})


def test_entry_reader_stops_at_control_flow_and_forgets_overwritten_registers():
    prefix = ('sll $t0, $a1, 3', 'addu $t0, $a0, $t0')
    assert not repair.evidence(assembly(*prefix, 'lw $t0, 0($sp)', 'lh $v0, 4($t0)'))
    assert not repair.evidence(assembly(*prefix, 'jal helper', 'lh $v0, 4($t0)'))


def test_unique_relocated_field_supports_single_global():
    source = 'extern char D_80000400[];\nint f(int i) { return *(short *)(D_80000400 + (i * 12)); }'
    target = {('$a0', 12): {'D_80000400': 2}}
    [(family, candidate)] = repair.global_variants(source, 'f', '', target)
    assert family == repair.FAMILY and '[i].value' in candidate
    target['$a1', 8] = {'D_80000400': 2}
    assert not repair.global_variants(source, 'f', '', target)


def test_scalar_array_uses_typed_record_at_the_same_byte_address():
    source = 'extern unsigned short table[];\nint f(int i) { return table[i * 6]; }'
    [(family, candidate)] = repair.global_variants(source, 'f', '', {('$a0', 12): {'table': 2}})
    assert family == repair.FAMILY and 'padding[10]' in candidate
    assert '*)table)[i].value' in candidate
    assert not repair.global_variants(source, 'f', '', {('$a0', 8): {'table': 2}})
