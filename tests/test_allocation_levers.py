"""Rewrites that only change which registers gcc 2.7.2 picks: operand order, statement order, written-out compound
assignments, declaration order; and record tables addressed by subscript, whose `addu` puts the index first."""
from decomprepair import allocation_lever_repairs as a
from decomprepair import row_subscript_repairs as r

ROW = '''void f(s32 arg0) {
    s32 temp_a0;
    u8 *temp_v1;

    temp_a0 = arg0 * 0x68;
    temp_v1 = (char *)((D_800E41DC)); temp_v1 += (s32)((temp_a0));
    if (*temp_v1 != 0) {
        *temp_v1 = 0;
        M2C_FIELD((temp_a0 + D_800E41DC), s8 *, 0x61) = 1;
    }
}
'''


def test_a_scaled_index_becomes_a_row_subscript():
    # An N64 function at 99.7%, off by `addu`'s operand order: exact as rows of bytes, with nothing else to infer.
    (family, out), = r.variants(ROW, 'f')
    assert family == 'row_subscript'
    assert 'if (((u8 (*)[0x68]) D_800E41DC)[arg0][0x0] != 0) {' in out
    assert '((s8 (*)[0x68]) D_800E41DC)[arg0][0x61] = 1;' in out
    assert 'temp_a0' not in out and 'temp_v1' not in out


def test_a_pointer_used_otherwise_is_kept():
    kept = ROW.replace('        *temp_v1 = 0;\n', '        g(temp_v1);\n')
    out = [t for _, t in r.variants(kept, 'f')]
    assert all('temp_v1 = ' in t for t in out)
    assert any('((s8 (*)[0x68]) D_800E41DC)[arg0][0x61] = 1;' in t for t in out)


def test_wider_fields_index_their_own_rows():
    source = 'void f(s32 i) {\n    s32 t;\n\n    t = i * 0x10;\n    M2C_FIELD((D + t), s32 *, 8) = 1;\n}\n'
    (_, out), = r.variants(source, 'f')
    assert '((s32 (*)[0x4]) D)[i][0x2] = 1;' in out


LEVER = '''void f(void) {
    u32 x;
    u32 y;

    x = A + B;
    C = x;
    D += (x >> 0x1F) + x;
}
'''


def test_each_lever_is_offered_alone():
    out = [t for _, t in a.variants(LEVER, 'f')]
    assert any('x = B + A;' in t for t in out)
    assert any('D += x + (x >> 0x1F);' in t for t in out)
    assert any('D = D + ((x >> 0x1F) + x);' in t for t in out)
    assert any('    D += (x >> 0x1F) + x;\n    C = x;' in t for t in out)
    assert any(t.index('u32 y;') < t.index('u32 x;') for t in out)
    # x is written by the first statement and read by the second: they don't swap
    assert not any('    C = x;\n    x = A + B;' in t for t in out)


def test_left_alone_without_a_body():
    assert a.variants('int f(void);\n', 'f') == []
    assert r.variants('void f(void) {\n    g();\n}\n', 'f') == []


def test_exposes_row_and_column_byte_strides_in_element_address():
    source = """
extern s32 grid[][7];
void f(int row, int column) {
    s32 *cell;
    cell = &grid[(row + 1)][lookup(column)];
    ++*cell;
}
"""
    [(family, candidate)] = r.variants(source, 'f')
    assert family == 'linear_row_address'
    assert '(char *)&grid' in candidate
    assert '((row + 1)) * sizeof(grid[0])' in candidate
    assert '(lookup(column)) * sizeof(grid[0][0])' in candidate


def test_leaves_shadowed_or_untyped_array_addresses_alone():
    source = """
extern s32 grid[][7];
void f(int row, int column) {
    s32 *cell;
    cell = &grid[row][column];
}
"""
    assert not r.variants(source.replace('    s32 *cell;', '    s32 grid[4][7];\n    s32 *cell;'), 'f')
    assert not r.variants(source.replace('    s32 *cell;', '    u32 *cell;'), 'f')
    assert not r.variants(source.replace('&grid[row][column]', '&grid[row]'), 'f')


def test_stages_repeated_reads_from_one_row_table():
    source = """
typedef struct { u8 v; } ByteField;
extern s32 grid[][7];
static inline u8 column(void *p) {
    return ((ByteField *) (((char *) p) + 1))->v;
}
int f(void *p) {
    s32 *cell;
    s32 value;
    value = grid[((ByteField *) (((char *) p) + 0))->v][column(p)];
    cell = &grid[((ByteField *) (((char *) p) + 0))->v][column(p)];
    return value + *cell;
}
"""
    [(family, candidate)] = r.staged_variants(source, 'f')
    assert family == 'staged_row_address'
    assert candidate.count('sizeof(grid[0])') == 2
    assert candidate.count('column(p)') == 2
    assert not r.staged_variants(source.replace('return ((ByteField', 'mutate(p); return ((ByteField'), 'f')
    assert not r.staged_variants(source.replace('u8 v', 'volatile u8 v'), 'f')


def test_two_plain_stores_to_different_offsets_of_one_record_are_swapped():
    source = """void f(void *obj)
{
  ((Field_s32 *) (((char *) obj) + 0x3C))->v = 0;
  ((Field_s32 *) (((char *) obj) + 0x28))->v = 0;
  obj->tail = 1;
  obj->head = 2;
}
"""
    out = [text for _, text in a.variants(source, 'f')]
    assert any(t.index('+ 0x28') < t.index('+ 0x3C') for t in out)
    assert any(t.index('obj->head = 2;') < t.index('obj->tail = 1;') for t in out)


def test_overlapping_or_computed_stores_are_not_swapped():
    overlapping = """void f(void *obj, int n)
{
  ((Field_s32 *) (((char *) obj) + 0x28))->v = 0;
  ((Field_s32 *) (((char *) obj) + 0x2A))->v = 0;
  obj->a = n;
  obj->a = 4;
  obj->b = load(n);
  obj->c = 4;
}
"""
    out = [text for _, text in a.variants(overlapping, 'f')]
    assert all(t.index('+ 0x28') < t.index('+ 0x2A') for t in out)
    assert all(t.index('obj->a = n;') < t.index('obj->a = 4;') for t in out)
    assert all(t.index('obj->b = load') < t.index('obj->c = 4;') for t in out)
