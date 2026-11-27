"""Two block copies into m2c's frame array, then the narrow counter and the record member its draft lost."""
from decomprepair.asm_member_view import variants as member_views
from decomprepair.element_pointer_direct_index import variants as element_direct
from decomprepair.guarded_masked_counter_for import variants as counter_for
from decomprepair.scratch_frame_records import variants as frame_records
from decomprepair.staged_store_rise import variants as staged

COPY = """    {d} = {dest};
    {s} = {src};
    do {{
        M2C_FIELD({d}, s32 *, 0) = M2C_FIELD({s}, s32 *, 0);
        M2C_FIELD({d}, s32 *, 4) = (s32) M2C_FIELD({s}, s32 *, 4);
        M2C_FIELD({d}, s32 *, 8) = (s32) M2C_FIELD({s}, s32 *, 8);
        M2C_FIELD({d}, s32 *, 0xC) = (s32) M2C_FIELD({s}, s32 *, 0xC);
        {s} += 0x10;
        {d} += 0x10;
    }} while ({s} != ({src} + {end}));
"""

DRAFT = ("""extern char gFirst[];
extern char gSecond[];

#define sp10 ((s32 *)(sp + 0x10))
#define sp40 (*(s32 *)(sp + 0x40))
#define sp44 (*(s32 *)(sp + 0x44))
void fill(void) {
    u8 sp[104];
    s32 *var_v0;
    s32 *var_v0_2;
    char *var_v1;
    char *var_v1_2;

""" + COPY.format(d='var_v1', dest='&sp10[0]', s='var_v0', src='gFirst', end='0x30')
         + COPY.format(d='var_v1_2', dest='&sp40', s='var_v0_2', src='gSecond', end='0x20')
         + """    M2C_FIELD(var_v1_2, s32 *, 0) = M2C_FIELD(var_v0_2, s32 *, 0);
    sp40 = 1;
    sp44 = 2;
    take(&(&sp10[0])[index()], &(&sp40)[index()]);
}
""")


def test_the_copies_become_assignments_to_records_in_the_frames_order():
    ((family, text),) = frame_records(DRAFT, 'fill')
    assert family == 'scratch_frame_records'
    assert 'u8 sp[' not in text and '#define' not in text and 'do {' not in text
    assert '    __repair_block30w __repair_stack10;\n    __repair_block24w __repair_stack40;\n' in text
    assert '__repair_stack10 = *(__repair_block30w *)(gFirst);' in text
    assert '__repair_stack40 = *(__repair_block24w *)(gSecond);' in text
    assert '__repair_stack40.data[0] = 1;\n    __repair_stack40.data[1] = 2;' in text
    assert '&__repair_stack10.data[index()]' in text  # the element itself, not through `&record.data[0]`


def test_a_frame_with_another_use_of_the_array_is_left_alone():
    assert frame_records(DRAFT.replace('sp40 = 1;', 'take(sp + 0x60, 0);'), 'fill') == []


COUNTED = """void queue(void) {
    s32 start;
    s32 temp_a0;
    s32 var_a0;
    s32 var_s0;

    start = (gPage - 1) * 6;
    var_s0 = start;
    var_a0 = var_s0 & 0xFFFF;
    if (var_a0 < (start + 6)) {
        do {
            if (gMode == 0) {
                use(gA[var_a0]);
            } else {
                temp_a0 = var_s0 & 0xFFFF;
                use(gB[temp_a0]);
            }
            var_s0 += 1;
            use(gFlag);
            var_a0 = var_s0 & 0xFFFF;
        } while (var_a0 < (((gPage - 1) * 6) + 6));
    }
    last(var_a0);
}
"""


def test_a_masked_counter_from_an_expression_is_the_narrow_for_loop():
    children = [text for _, text in counter_for(COUNTED, 'queue')]
    assert len(children) == 2
    inline = children[0]
    assert 'u16 var_a0;' in inline and 'var_s0' not in inline and 'start' not in inline
    assert 'for (var_a0 = (gPage - 1) * 6; var_a0 < (((gPage - 1) * 6) + 6); var_a0++) {' in inline
    assert 'use(gB[var_a0]);' in inline and 'temp_a0' not in inline
    assert 'last(var_a0);' in inline
    assert 'for (var_a0 = start;' in children[1]


def test_a_counter_read_after_its_step_is_left_alone():
    assert counter_for(COUNTED.replace('use(gFlag);', 'use(var_s0);'), 'queue') == []
    assert counter_for(COUNTED.replace('var_a0 < (start + 6)', 'var_a0 < (start + 5)'), 'queue') == []


ASM = """lui $v0, %hi(gVolumes)
addiu $s1, $v0, %lo(gVolumes)
lui $v0, %hi(gOther)
addiu $v0, $v0, %lo(gOther)
lw $v0, 0x0($v0)
sh $a1, 0x4($v0)
lhu $a1, 0x2($s1)
"""
NAMED = """extern char gVolumes[];
extern char gOther[];
extern unsigned short D_80012346;

void play(void) {
    start(D_80012346);
}
"""


def test_a_word_the_assembly_never_names_is_the_member_of_the_global_it_is_read_off():
    ((family, text),) = member_views(NAMED, 'play', ASM)
    assert family == 'asm_member_view'
    assert 'typedef struct { unsigned char head[0x2]; unsigned short field; } __repair_view2_u16;' in text
    assert 'start((((__repair_view2_u16 *)&gVolumes)->field));' in text
    assert member_views(NAMED, 'play', ASM + 'lhu $a0, %lo(D_80012346)($a0)\n') == []


def test_element_pointers_read_with_a_star_are_inlined_one_by_one_and_all_at_once():
    source = """void pick(s32 i) {
    s32 *a;
    s32 *b;
    s32 got;

    if (gMode == 0) {
        a = &first.data[i];
        M2C_FIELD(gOut, s32 *, 0) = *a;
        got = *a;
    } else {
        b = &second.data[i];
        got = (s32) *b;
    }
    use(got);
}
"""
    children = [text for _, text in element_direct(source, 'pick')]
    assert len(children) == 3
    assert 's32 *a;' not in children[0] and 's32 *b;' not in children[0]
    assert 'got = first.data[i];' in children[0] and 'got = (s32) second.data[i];' in children[0]


def test_a_member_of_a_view_of_a_global_is_read_ahead_of_the_store_before_it():
    source = """typedef struct { unsigned char head[2]; unsigned short field; } View;
typedef struct { s32 key; u16 value; } Entry;
extern s32 gVolumes;

void put(Entry *entry, s32 id) {
    entry->key = id;
    entry->value = (u16) (((View *) &gVolumes)->field);
}
"""
    text = staged(source, 'put')[0][1]
    assert '__rise = (u16) (((View *) &gVolumes)->field);\n    entry->key = id;\n    entry->value = __rise;' in text
