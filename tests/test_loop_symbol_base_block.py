"""A byte array's address added to an index in a nested loop's guarded block, kept out of loop hoisting."""
from decomprepair import loop_symbol_base_block as b

HELD = '''extern u8 D_8011F118[];
extern s32 D_8011F338;

void f(void) {
    u16 __repair_i;
    u8 *__base_D_8011F118;
    void *temp_s0;

    __base_D_8011F118 = D_8011F118;

    for (__repair_i = 0; __repair_i < 3; __repair_i++) {
        temp_s0 = (void *) D_8011F338;
        if (temp_s0 != NULL) {
            g(temp_s0, (__repair_i * 0xC) + __base_D_8011F118, 1);
        }
    }
}
'''

RAW = HELD.replace('    u8 *__base_D_8011F118;\n', '').replace('    __base_D_8011F118 = D_8011F118;\n\n', '') \
    .replace('(__repair_i * 0xC) + __base_D_8011F118', '(__repair_i * 0xC) + D_8011F118')


def test_a_held_base_is_set_twice_with_the_index_computed_first():
    texts = [t for _, t in b.variants(HELD, 'f')]
    assert texts
    first = texts[0]
    assert '__base_D_8011F118 = 0;' in first
    assert '__base_D_8011F118 = D_8011F118;' in first
    assert first.index('__index_D_8011F118 = __repair_i * 0xC;') < first.index('__base_D_8011F118 = D_8011F118;')
    assert 'g(temp_s0, __base_D_8011F118 + __index_D_8011F118, 1);' in first
    assert first.index('__base_D_8011F118 = 0;') < first.index('for (')
    assert 's32 __index_D_8011F118;' in first


def test_the_other_order_of_the_assignments_is_offered():
    texts = [t for _, t in b.variants(HELD, 'f')]
    assert any(t.index('__base_D_8011F118 = D_8011F118;') < t.index('__index_D_8011F118 = ') for t in texts)


def test_the_drafts_own_sum_gets_a_local_after_the_declarations():
    texts = [t for _, t in b.variants(RAW, 'f')]
    assert texts
    first = texts[0]
    assert first.index('void *temp_s0;') < first.index('__base_D_8011F118 = 0;') < first.index('for (')
    assert 'g(temp_s0, __base_D_8011F118 + __index_D_8011F118, 1);' in first


def test_a_sum_outside_every_loop_is_left_alone():
    flat = HELD.replace('for (__repair_i = 0; __repair_i < 3; __repair_i++) {', '{')
    assert b.variants(flat, 'f') == []


def test_a_wider_element_is_left_alone():
    assert b.variants(HELD.replace('extern u8 D_8011F118[]', 'extern s32 D_8011F118[]'), 'f') == []
