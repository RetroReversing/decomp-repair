from decomprepair import record_slot_rows as rows

MACRO = '''#define FIELD(base, type, offset) (*(type *)((char *)(base) + (offset)))
#define SLOT() FIELD(gInfo, s32, (pick(FIELD(p, s8, 0x182)) & 0xFFFF) * 24)
extern s32 pick(s32);
extern u8 gInfo[];
extern u8 gFlags[];
extern u8 gTable[];

s32 f(void *p, s32 n) {
    s32 a;
    s32 b;
    s32 count;
    s16 i;

    a = FIELD(gFlags, u16, SLOT() * 12) & 3;
    b = SLOT();
    count = 0;
    i = 0;
    do {
        if (gTable[i * 24] == n) {
            count += 1;
        }
        i += 1;
    } while (i < b);
    return a + count;
}
'''


def texts(source, name):
    return [text for _, text in rows.variants(source, name)]


def test_every_byte_strided_table_becomes_typed_rows_in_one_child():
    *singles, combined = texts(MACRO, 'f')
    assert len(singles) == 3
    assert 'typedef struct { s32 f0; u8 pad[20]; } Row_gInfo;' in combined
    assert 'extern Row_gInfo gInfo[];' in combined
    assert 'typedef struct { u16 f0; u8 pad[10]; } Row_gFlags;' in combined
    assert 'typedef struct { u8 f0; u8 pad[23]; } Row_gTable;' in combined
    # the macro's own access, the access with a call in its index, and the subscript
    assert '#define SLOT() gInfo[pick(FIELD(p, s8, 0x182)) & 0xFFFF].f0' in combined
    assert 'a = gFlags[SLOT()].f0 & 3;' in combined
    assert 'if (gTable[i].f0 == n)' in combined
    assert 'gTable[i * 24]' not in combined


def test_each_table_alone_is_a_child_that_compiles_as_the_rest_of_the_source():
    singles = texts(MACRO, 'f')[:-1]
    assert [('Row_gInfo' in t, 'Row_gFlags' in t, 'Row_gTable' in t) for t in singles] == [
        (True, False, False), (False, True, False), (False, False, True)]
    assert 'gTable[i * 24]' in singles[0] and 'gInfo[' in singles[0]


POINTER = '''extern u8 gMask[];
extern u8 gWords[];

void g(u16 k) {
    *(u16 *)(gMask + (k & 0xFFFF) * 12) |= 0x10;
    *((s32 *) (((char *) gWords) + k * 16)) = 1;
}
'''


def test_pointer_plus_byte_index_spellings_are_accesses_too():
    out = texts(POINTER, 'g')
    assert out
    assert 'gMask[k & 0xFFFF].f0 |= 0x10;' in out[0]
    both = out[-1]
    assert 'gWords[k].f0 = 1;' in both


def test_a_table_with_another_use_stride_or_misaligned_field_is_left_alone():
    assert not texts(MACRO.replace('a = FIELD(gFlags', 'h(gFlags); a = FIELD(gFlags'), 'f')[-1:] or \
        'Row_gFlags' not in texts(MACRO.replace('a = FIELD(gFlags', 'h(gFlags); a = FIELD(gFlags'), 'f')[-1]
    assert not texts(MACRO.replace('gTable[i * 24]', 'gTable[i * 24 + 1]'), 'f')[-1:] or \
        'Row_gTable' not in texts(MACRO.replace('gTable[i * 24]', 'gTable[i * 24 + 1]'), 'f')[-1]
    assert 'Row_gFlags' not in ''.join(texts(MACRO.replace('* 12)', '* 3)'), 'f'))
    assert not texts('extern u8 gT[];\nvoid k(void) { gT[2] = 1; }\n', 'k')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    assert 'record_slot_rows' in {r.module for r in registry.declared()}
    assert all(not registry.problems(r) for r in registry.declared() if r.module == 'record_slot_rows')
