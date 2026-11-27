from decomprepair.indexed_record_paired_reads import variants

SOURCE = '''
void f(void *root, int index, void *voice) {
    void *address;
    int mix;
    float pitch;
    address = *(u8 **)((u8 *) root + 0x60) + index * 0x10;
    mix = (u8)(((u8 *)address)[0xA]);
    pitch = M2C_FIELD(voice, f32 *, 0x28) * M2C_FIELD(address, f32 *, 0xC);
}
'''
ASM = '''
    sll $v0, $s5, 4
    addu $v0, $v0, $v1
    lwc1 $f0, 0xc($v0)
    mul.s $f20, $f20, $f0
    lbu $s0, 0xa($v0)
'''


def test_offers_both_direct_fields():
    result = variants(SOURCE, 'f', ASM, ['-mgp32'])
    assert len(result) == 1
    child = result[0][1]
    assert 'address =' not in child
    assert '))[index].byte' in child
    assert '))[index].real' in child
    assert 'u8 pad[10]; u8 byte; u8 pad2; f32 real;' in child


def test_rejects_unwitnessed_and_impure_cases():
    assert variants(SOURCE, 'f', ASM.replace('0xa($v0)', '0xa($v1)'), ['-mgp32']) == []
    assert variants(SOURCE, 'f', ASM, []) == []
    assert variants(SOURCE.replace('M2C_FIELD(voice,', 'change(voice) * M2C_FIELD(voice,'), 'f', ASM, ['-mgp32']) == []
    assert variants(SOURCE.replace('int mix;', 'int mix; volatile int x;'), 'f', ASM, ['-mgp32']) == []
    assert variants(SOURCE.replace('int mix;', 'int mix; use(address);'), 'f', ASM, ['-mgp32']) == []
