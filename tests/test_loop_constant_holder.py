from decomprepair import loop_constant_holder as holder

SOURCE = '''extern u8 gScene[];
extern void *gOrigins[];
extern u8 gActive[];

void f(void *list, s32 kind) {
    u32 n;
    s32 hit;

    n = 0;
    do {
        n += 1;
    } while (n < 4);
    if (list != NULL) {
        u8 *active = gActive;
        void **origins = gOrigins;
        u8 *scene = gScene;
        do {
            hit = 0;
            if (*(s16 *)((char *)list + 0x7A) == 3) {
                hit = 1;
            }
            if (*scene == 3 && origins[hit] == list && active[hit] != 0) {
                hit = 2;
            }
            list = *(void **)((char *)list + 0x10);
        } while (list != NULL);
    }
}
'''


def test_the_literal_goes_through_the_finished_counter_before_the_pointers():
    out = [text for _, text in holder.variants(SOURCE, 'f')]
    assert out
    text = out[0]
    assert 'n = 3;' in text
    assert text.index('n = 3;') < text.index('active = gActive;')
    assert '== n)' in text and '*scene == n' in text
    assert '== 3' not in text
    assert text.count('{') == text.count('}')
    assert 'u8 *active;\n        void **origins;\n        u8 *scene;\n' in text


def test_every_order_of_the_pointer_assignments_is_offered():
    out = [text for _, text in holder.variants(SOURCE, 'f')]
    orders = {tuple(t.index(name + ' = ') for name in ('active', 'origins', 'scene')) for t in out}
    assert len(orders) == 6


def test_a_counter_the_block_reads_or_that_is_read_later_is_left_alone():
    assert not holder.variants(SOURCE.replace('hit = 0;', 'hit = n;'), 'f')
    assert not holder.variants(SOURCE.replace('hit = 0;', 'hit = 0;').replace('    }\n}\n', '    }\n    use(n);\n}\n'), 'f')
    assert not holder.variants(SOURCE.replace('== 3) {\n                hit = 1;', '== 5) {\n                hit = 1;'), 'f')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'loop_constant_holder' in declared and not registry.problems(declared['loop_constant_holder'])
