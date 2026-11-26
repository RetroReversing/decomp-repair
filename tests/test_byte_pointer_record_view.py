"""byte_pointer_record_view: byte pointers read through `*(T *) (p + K)` casts, as records, with their literal locals.

Synthetic shape of the 72-instruction SN64 GCC 2.8.1 object state handler (70 -> 0): an object parameter and a global
player pointer copied to a local, read through raw casts with `volatile` pins, a constant local for `+ 0x8000`, and a
third call argument the callee's matched C does not take."""
from decomprepair import byte_pointer_record_view as s

SOURCE = '''s32 func_80023874(s32, s32, s32);
s32 func_8004303C(void *);
extern u8 *D_800B3960;
extern u8 *D_800B3964;
s32 func_8007E1AC(void *);

s32 handler(u8 *obj) {
    s32 t;
    u8 *p;
    f32 f;
    s32 k;

    if (*(s32 *) (obj + 0x88) == 0) {
        *(s32 *) (obj + 0x88) = 1;
    }
    t = *(s32 *) (D_800B3960 + 0x10);
    *(s32 *) (obj + 0x10) = t;
    if (func_80023874(0x801, 0, t) != 0) {
        return 0;
    }
    k = *(s32 *) (D_800B3964 + 0x7C);
    if (k != 4) {
        return 0;
    }
    p = D_800B3960;
    f = *(f32 *) (obj + 0xC) - 4500.0f;
    *(u8 * volatile *) (p + 0xA8) = obj;
    *(volatile f32 *) (p + 0xC) = f;
    k = 0x8000;
    *(s32 *) (obj + 0x10) = *(volatile s32 *) (p + 0x10) + k;
    func_8004303C(*(void **) (obj + 0xA8));
    *(void **) (obj + 0xD8) = func_8007E1AC;
    return 0;
}
'''

CALLEES = 'Obj *func_80023874(s32 arg0, Obj *arg1) {\n    return 0;\n}\n'


def test_records_pins_and_the_literal_local():
    found = s.variants(SOURCE, 'handler')
    assert found and all(family == s.FAMILY for family, _ in found)
    texts = [text for _, text in found if text.count('typedef struct Rec_') == 3]
    assert len(texts) == 4  # pins kept / dropped, each also with the literal inlined
    for text in texts:
        assert 'typedef struct Rec_handler_obj {' in text and 'typedef struct Rec_handler_D_800B3960 {' in text
        assert 'extern Rec_handler_D_800B3960 *D_800B3960;' in text and 'Rec_handler_D_800B3960 *p;' in text
        assert 's32 handler(Rec_handler_obj *obj) {' in text
        assert text.index('typedef struct Rec_handler_D_800B3960') < text.index('extern Rec_handler_D_800B3960')
        assert '    f32 mC;\n    s32 m10;\n    u8 pad14[0x74];\n    s32 m88;' in text
        assert 'void * mA8;' in text and 'obj->mD8 = func_8007E1AC;' in text
        assert 'func_8004303C(obj->mA8);' in text and 'k = D_800B3964->m7C;' in text
        assert '(obj +' not in text and '(p +' not in text
    pinned, pinned_literal, plain, plain_literal = texts
    assert '(*(void * volatile *) &p->mA8) = obj;' in pinned and '(*(volatile f32 *) &p->mC) = f;' in pinned
    assert 'volatile' not in plain and '    p->mA8 = obj;\n    p->mC = f;\n' in plain
    assert 'k = 0x8000;' in plain and 'p->m10 + k;' in plain
    assert 'k = 0x8000;' not in plain_literal and 'obj->m10 = p->m10 + 0x8000;' in plain_literal
    assert 'k = 0x8000;' not in pinned_literal and '(*(volatile s32 *) &p->m10) + 0x8000;' in pinned_literal


def test_the_callee_arity_trim_is_offered_with_the_records():
    texts = [text for _, text in s.variants(SOURCE, 'handler', CALLEES) if text.count('typedef struct Rec_') == 3]
    assert len(texts) == 8
    trimmed = texts[4:]
    for text in trimmed:
        assert 'func_80023874(0x801, 0) != 0' in text and 's32 func_80023874(s32, s32);' in text
    assert 'obj->m10 = p->m10 + 0x8000;' in trimmed[3] and 'volatile' not in trimmed[3]


def _records_of(text):
    return {line.split()[2] for line in text.splitlines() if line.startswith('typedef struct Rec_')}


def test_one_group_alone_comes_after_all_of_them():
    texts = [text for _, text in s.variants(SOURCE, 'handler')]
    alone = [_records_of(text) for text in texts if len(_records_of(text)) == 1]
    assert {'Rec_handler_obj'} in alone and {'Rec_handler_D_800B3960'} in alone
    assert len(_records_of(texts[0])) == 3


def test_an_ineligible_pointer_keeps_its_casts_and_the_others_are_records():
    for text in (SOURCE.replace('func_8004303C(*(void **) (obj + 0xA8));', 'func_8004303C(obj + 4);'),
                 SOURCE.replace('    return 0;\n}\n', '    return obj[3];\n}\n'),
                 SOURCE.replace('func_8004303C(*(void **) (obj + 0xA8));', 'func_8004303C(&obj);')):
        found = [t for _, t in s.variants(text, 'handler')]
        assert found and all('Rec_handler_obj' not in t and '*(s32 *) (obj + 0x88) == 0' in t for t in found)
        assert any('Rec_handler_D_800B3960' in t for t in found)


def test_casts_that_disagree_or_overlap_leave_that_group():
    for text, group in ((SOURCE.replace('t = *(s32 *) (D_800B3960 + 0x10);', 't = *(u16 *) (D_800B3960 + 0x10);'),
                         'Rec_handler_D_800B3960'),
                        (SOURCE.replace('k = *(s32 *) (D_800B3964 + 0x7C);', 'k = *(s32 *) (D_800B3964 + 0x7E);'),
                         'Rec_handler_D_800B3964')):
        found = [t for _, t in s.variants(text, 'handler')]
        assert found and all(group not in _records_of(t) for t in found)


def test_nothing_eligible_declines():
    text = 'void f(u8 *p) {\n    *(s32 *) (p + 4) = 0;\n    g(&p);\n}\n'
    assert s.variants(text, 'f') == []


def test_a_literal_local_read_twice_is_left():
    text = SOURCE.replace('    return 0;\n}\n', '    return k;\n}\n')
    plain = [t for _, t in s.variants(text, 'handler') if len(_records_of(t)) == 3]
    assert len(plain) == 2 and all('k = 0x8000;' in t for t in plain)
