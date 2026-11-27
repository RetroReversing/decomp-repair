from decomprepair.target_pointer_record_index import variants

SOURCE = '''void f(void *p, u8 index) {
    void *address;
    u8 *value;
    address = (u8 *) p + 0x60;
    address = *(u8 **) address + index * 0x10;
    value = *(u8 **) address;
    use(value);
}
'''
ASM = '''lw $v1, 0x60($s2)
sll $v0, $s5, 4
addu $v0, $v0, $v1
lw $s0, 0($v0)
'''


def test_indexed_pointer_record():
    out = variants(SOURCE, 'f', ASM, ('-mgp32',))
    assert len(out) == 1
    text = out[0][1]
    assert 'typedef struct { u8 *pointer; u8 reserved[12]; } IndexedPointerRecord;' in text
    assert '[index].pointer;' in text
    assert 'void *address;' not in text


def test_requires_target_and_no_other_address_uses():
    assert not variants(SOURCE, 'f', '', ('-mgp32',))
    assert not variants(SOURCE, 'f', ASM, ())
    assert not variants(SOURCE.replace('use(value);', 'use(value, address);'), 'f', ASM, ('-mgp32',))
    assert not variants(SOURCE, 'f', ASM.replace('0x60', '0x64'), ('-mgp32',))
