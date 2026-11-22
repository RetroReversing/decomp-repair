from decomprepair import measured_loop_key_copy as repair

HEADER = 'typedef signed int s32; typedef unsigned int u32;'
SOURCE = '''void f(void *records, s32 count, s32 key, s32 value) {
    s32 i;
    i = 0;
loop:
    if (*(s32 *)records != key) {
        i += 1;
    } else {
        *(s32 *)records = value;
    }
    records = (char *)records + 12;
    if (i < count) {
        goto loop;
    }
}
'''
ROWS = [('r', 'move $a1, $v1', 'move $t0, $v1'),
        ('r', 'move $t0, $zero', 'move $a0, $zero'),
        (' ', 'bnel $v0, $a2, 80', 'bnel $v0, $a2, 80')]


def variants(source=SOURCE, header=HEADER, rows=ROWS, flags=('-mgp32',)):
    return repair.variants(source, 'f', header, rows, flags)


def test_copies_single_loop_comparison_key():
    (_, candidate), = variants()
    assert 's32 __repair_loop_key;' in candidate
    assert '__repair_loop_key = key;' in candidate
    assert '*(s32 *)records != __repair_loop_key' in candidate
    assert candidate.index('__repair_loop_key = key;') < candidate.index('loop:')


def test_requires_loop_key_abi_and_observable_target_evidence():
    assert not variants(rows=ROWS[:2])
    assert not variants(flags=('-mabi=64',))
    assert not variants(source=SOURCE.replace('goto loop;', 'return;'))
    assert not variants(source=SOURCE.replace('!= key', '!= key++'))
    assert not variants(source=SOURCE.replace('!= key', '!= key + __LINE__'))
    assert not variants(source=SOURCE.replace('!= key', '!= hidden(key)'), header=HEADER + '\n#define hidden(x) (x)')
    assert not variants(header=HEADER.replace('signed int s32', 'volatile int s32'))
