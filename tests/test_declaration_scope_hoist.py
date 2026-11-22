"""A local declared in an inner block, moved to the function's declarations in the order of its `spXX` name.

Synthetic shape of the 851-instruction ray test: m2c's stack-offset locals (`sp164` ...) hold the addresses of scratch
vectors across calls; two of them had been declared at the top of the block that uses them, which numbered their
pseudos, and so their spill slots, after all the others."""
from decomprepair import declaration_scope_hoist as h

SOURCE = '''s32 cast(f32 *a, void *b)
{
    f32 *sp164;
    f32 *sp16C;
    f32 *sp17C;
    f32 *sp18C;
    s32 count;

    count = 0;
    if (b != NULL) {
        f32 *sp174;
        f32 *sp184;
        sp164 = &a[0];
        sp16C = &a[1];
        sp174 = &a[2];
        sp17C = &a[3];
        sp184 = &a[4];
        sp18C = &a[5];
        count = use(sp164, sp16C, sp174, sp17C, sp184, sp18C);
    }
    return count;
}
'''


def _texts(source=SOURCE):
    found = h.variants(source, 'cast')
    assert all(family == h.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_every_hoisted_local_goes_between_its_neighbours_by_offset():
    both = _texts()[0]
    assert '    f32 *sp164;\n    f32 *sp16C;\n    f32 *sp174;\n    f32 *sp17C;\n    f32 *sp184;\n    f32 *sp18C;\n    s32 count;\n' in both
    assert 'if (b != NULL) {\n        sp164' in both


def test_each_local_is_also_offered_alone():
    texts = _texts()
    assert any('    f32 *sp16C;\n    f32 *sp174;\n    f32 *sp17C;\n' in t and '        f32 *sp184;\n' in t for t in texts[1:])


def test_a_name_without_an_offset_goes_after_the_last_declaration():
    text = SOURCE.replace('f32 *sp174;', 'f32 *cursor;').replace('sp174', 'cursor')
    assert any('    s32 count;\n    f32 *cursor;\n' in t for t in _texts(text))


def test_a_local_whose_address_is_taken_stays():
    text = SOURCE.replace('sp174 = &a[2];', 'sp174 = &a[2]; use(&sp184);')
    assert all('        f32 *sp184;' in t for t in _texts(text))


def test_a_name_declared_twice_stays():
    text = SOURCE.replace('    f32 *sp164;\n', '    f32 *sp164;\n    f32 *sp174;\n', 1)
    assert all('        f32 *sp174;' in t for t in _texts(text))


def test_a_function_without_inner_declarations_is_left_alone():
    flat = SOURCE.replace('        f32 *sp174;\n        f32 *sp184;\n', '')
    assert h.variants(flat, 'cast') == []


def test_the_members_of_a_local_record_are_not_locals():
    record = SOURCE.replace('    s32 count;\n', '    struct {\n        f32 total;\n        f32 spare;\n    } work;\n    s32 count;\n')
    assert all('    f32 total;' not in t.replace('        f32 total;', '') for t in _texts(record))
    assert all('        f32 total;\n        f32 spare;\n    } work;' in t for t in _texts(record))
