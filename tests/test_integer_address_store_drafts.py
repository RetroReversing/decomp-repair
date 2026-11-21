from decomprepair import integer_address_store_drafts as drafts

ASM = '''glabel f
/* 0 80000000 A4400000 */  sh         $zero, 0x0($v0)
/* 4 80000004 AFB50054 */  sw         $s5, 0x54($sp)
/* 8 80000008 AC450004 */  sw         $a1, 0x4($v0)
/* c 8000000c A4400000 */  sh         $zero, 0x0($v1)
'''
SOURCE = '''void f(void) {
    *((*count * 0xA10) + base) = 0;
}
'''


def test_the_store_gets_each_width_the_target_uses_most_frequent_first():
    results = [text for _, text in drafts.variants(SOURCE, 'f', ASM)]
    assert results[0] == SOURCE.replace('*((', '*(u16 *)((')
    assert any('(s32 *)' in text for text in results) and len(results) == 2  # the stack store is not counted


def test_a_typed_or_plain_pointer_store_is_left_alone():
    for source in ('void f(void) {\n    *(u16 *)((*count * 0xA10) + base) = 0;\n}\n',
                   'void f(u8 *p) {\n    *(p) = 0;\n}\n'):
        assert drafts.variants(source, 'f', ASM) == []


def test_no_store_through_a_register_means_no_candidate():
    assert drafts.variants(SOURCE, 'f', 'glabel f\n/* 0 80000000 AFB50054 */  sw $s5, 0x54($sp)\n') == []
