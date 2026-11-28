import re

from decomprepair.chain_value_stage import FAMILY, variants
from decomprepair.independent_statement_swap import variants as swaps

SOURCE = """typedef struct Obj {
    s32 total;
    s32 frames;
    u8 r;
    u8 g;
    u8 b;
} Obj;

void fade(Obj *obj) {
    obj->total += 0x28;
    obj->frames++;
    obj->r = obj->g = obj->b -= 2;
    if (obj->b < 0x20 || gDone != 0) {
        stop(obj);
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(source):
    return [_flat(text) for family, text in variants(source, 'fade') if family == FAMILY]


def test_the_chain_value_is_staged_in_a_local_of_the_fields_type():
    reread, plain = _found(SOURCE)
    assert 'u8 staged_value;' in reread
    assert 'staged_value = obj->b - 2; obj->r = obj->g = obj->b = staged_value;' in reread
    assert 'if (staged_value < 0x20 || gDone != 0)' in reread
    assert 'if (obj->b < 0x20 || gDone != 0)' in plain


def test_a_test_that_calls_or_writes_keeps_reading_the_field():
    assert len(_found(SOURCE.replace('gDone != 0', 'done() != 0'))) == 1
    assert len(_found(SOURCE.replace('gDone != 0', 'obj->b++ != 0'))) == 1


def test_an_unknown_or_ambiguous_field_type_declines():
    assert not _found(SOURCE.replace('    u8 b;\n', ''))
    assert not _found(SOURCE.replace('    u8 b;\n', '    f32 b;\n'))
    assert not _found(SOURCE + 'typedef struct Other { s16 b; } Other;\n')


def test_a_lone_increment_trades_places_with_its_neighbour():
    found = [_flat(text) for _, text in swaps(SOURCE, 'fade')]
    assert any('obj->frames++; obj->total += 0x28;' in text for text in found)
