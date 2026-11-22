from decomprepair import counter_append_scope_repairs as repair

SOURCE = '''typedef struct
{
    s8 flag;
    u8 pad[7];
} Slot;
extern Slot D_slots[];
extern u8 D_keys[];
extern u8 D_count;
void f(void *key, s32 flag)
{
    s32 off;
    if (D_count < 8)
    {
        do
        {
            D_slots[D_count].flag = flag; off = D_count * 8;
            *((void **) (D_keys + off)) = key;
        }
        while (0);
        D_count += 1;
    }
}
'''


def test_one_scaled_index_a_counter_copy_and_the_bump_inside_the_scope():
    found = repair.variants(SOURCE, 'f')
    assert [family for family, _ in found] == ['counter_append_scope']
    text = found[0][1]
    assert 's32 __repair_append_count;' in text
    assert ('__repair_append_offset = D_count * 8; *((s8 *) ((char *) D_slots + __repair_append_offset)) = flag;\n'
            '            __repair_append_count = D_count;\n'
            '            *((void **) (D_keys + __repair_append_offset)) = key;\n'
            '            D_count = __repair_append_count + 1;\n'
            '        }\n        while (0);') in text
    assert 'D_count += 1;' not in text


def test_a_table_whose_field_is_not_the_first_member_or_a_counter_used_in_the_values_is_left_alone():
    later = SOURCE.replace('s8 flag;\n    u8 pad[7];', 'u8 pad[4];\n    s8 flag;')
    uses = SOURCE.replace('= flag;', '= D_count;')
    for source in (later, uses):
        assert not repair.variants(source, 'f')
