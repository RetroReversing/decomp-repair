"""pointer_walk_to_index / index_to_pointer_walk: a stepped record pointer beside a counter, and the indexed loop."""
from decomprepair import pointer_walk_to_index as pwi
from decomprepair import registry

WALK = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s32 count;
extern void *table;

s32 func_80021060(s32 arg0, f32 arg1) {
    s32 var_a2;
    s32 var_a1;
    void *var_v1;

    var_a2 = 0;
    var_a1 = 0;
    if (count > 0) {
        var_v1 = table;
        do {
            var_a2 += 1;
            if (M2C_FIELD(var_v1, s32 *, 0x14) == arg0) {
                var_a1 += 1;
                M2C_FIELD(var_v1, f32 *, 0) = arg1 + M2C_FIELD(var_v1, f32 *, 0x60);
            }
            var_v1 += 0x13C;
        } while (var_a2 < count);
    }
    return var_a1;
}
'''
NAME = 'func_80021060'


def forward(source=WALK, header=''):
    return [child for family, child in pwi.variants(source, NAME, header) if family == pwi.FAMILY]


def test_the_byte_stepped_pointer_becomes_the_counter_indexing_its_base():
    out = forward()
    assert len(out) == 2
    first = out[0]  # the counter's step stays at the top: its uses are one behind
    assert 'M2C_FIELD(var_v1, s32 *, (var_a2 - 1) * 0x13C + 0x14)' in first
    assert 'M2C_FIELD(var_v1, f32 *, (var_a2 - 1) * 0x13C)' in first
    assert 'var_v1 += 0x13C' not in first and 'var_a2 += 1;' in first and 'var_v1 = table;' in first
    moved = out[1]  # the counter's step moves to the end of the body: its uses are exact
    assert 'M2C_FIELD(var_v1, s32 *, var_a2 * 0x13C + 0x14)' in moved
    body = moved[moved.index('do {'):moved.index('} while')]
    assert body.rstrip().endswith('var_a2 += 1;') and moved.count('var_a2 += 1;') == 1


def test_a_typed_record_pointer_stepped_by_one_indexes_the_type_itself():
    source = '''typedef struct Rec { s32 a; s32 b; } Rec;
extern Rec *tab;
void f(s32 n) {
    s32 i;
    Rec *p;

    i = 0;
    p = tab;
    while (i < n) {
        p->a = p->b;
        *p = *p;
        i++;
        p++;
    }
}
'''
    out = [c for fam, c in pwi.variants(source, 'f') if fam == pwi.FAMILY]
    assert out and 'p[i].a = p[i].b;' in out[0] and 'p[i] = p[i];' in out[0] and 'p++;' not in out[0]


def test_nothing_is_offered_when_the_pointer_or_counter_escapes_the_pattern():
    assert forward(WALK.replace('return var_a1;', 'return var_v1;')) == []  # the pointer is read after the loop
    assert forward(WALK.replace('var_a2 = 0;', 'var_a2 = 1;')) == []  # the counter does not start at zero
    assert forward(WALK.replace('var_a1 += 1;', 'var_a1 += 1;\n                continue;')) == []
    assert forward(WALK.replace('M2C_FIELD(var_v1, f32 *, 0) =', 'func(var_v1), M2C_FIELD(var_v1, f32 *, 0) =')) == []
    assert forward(WALK.replace('var_v1 += 0x13C;', 'var_v1 += var_a1;')) == []
    assert forward(WALK.replace('void *var_v1;', 'Rec *var_v1;')) == []  # a record type steps only by one


def test_the_field_macro_the_source_defines_counts_too():
    source = WALK.replace('M2C_FIELD', 'F').replace('#define F(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))',
                                                     '#define F(p, T, o) (*(T)((s8 *)(p) + (o)))')
    assert forward(source) and 'F(var_v1, s32 *, var_a2 * 0x13C + 0x14)' in forward(source)[1]


REVERSE = '''typedef struct Rec { s32 a; s32 b; } Rec;
extern Rec *D_8017B20C;
extern s32 D_8017B204;

s32 func_8008D804(s32 id) {
    s32 i;
    s32 n;

    n = 0;
    for (i = 0; i < D_8017B204; i++) {
        if (D_8017B20C[i].a == id) {
            D_8017B20C[i].b = id;
            n++;
        }
    }
    return n;
}
'''


def reverse(source=REVERSE):
    return [child for family, child in pwi.variants(source, 'func_8008D804') if family == pwi.REVERSE_FAMILY]


def test_an_indexed_loop_becomes_a_cursor_stepped_beside_the_counter():
    out = reverse()
    assert len(out) == 1
    child = out[0]
    assert 'Rec *cur_D_8017B20C;' in child and 'cur_D_8017B20C = D_8017B20C;\n    for (i = 0; i < D_8017B204; i++, cur_D_8017B20C++) {' in child
    assert 'if (cur_D_8017B20C->a == id)' in child and 'cur_D_8017B20C->b = id;' in child


def test_a_start_other_than_zero_takes_the_address_of_that_element_and_a_whole_record_is_dereferenced():
    child = reverse(REVERSE.replace('i = 0; i <', 'i = 2; i <').replace('D_8017B20C[i].b = id;', 'D_8017B20C[i] = D_8017B20C[i];'))[0]
    assert 'cur_D_8017B20C = &D_8017B20C[2];' in child and '(*cur_D_8017B20C) = (*cur_D_8017B20C);' in child


def test_no_cursor_when_the_index_is_used_otherwise_or_a_global_changes_under_a_call():
    assert reverse(REVERSE.replace('n++;', 'n += i;')) == []
    assert reverse(REVERSE.replace('n++;', 'func(n);')) == []  # a call may change the global table pointer
    assert reverse(REVERSE.replace('n++;', 'D_8017B20C = 0;')) == []
    assert reverse(REVERSE.replace('D_8017B20C[i].b = id;', 'D_8017B20C[i + 1].b = id;')) == []
    local = REVERSE.replace('extern Rec *D_8017B20C;\n', '').replace('s32 id) {', 's32 id, Rec *D_8017B20C) {').replace(
        'n++;', 'func(n);')
    assert reverse(local)  # a parameter is not changed by the call


def test_it_is_registered():
    repair = {r.module: r for r in registry.declared()}['pointer_walk_to_index']
    assert not registry.problems(repair) and repair.families == pwi.FAMILIES
