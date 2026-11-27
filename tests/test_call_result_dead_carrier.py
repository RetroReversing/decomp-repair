from decomprepair import registry
from decomprepair.call_result_dead_carrier import CARRIER, INLINE, variants

SOURCE = '''void update(Thing *self) {
    Item *item;
    s32 shade;
    s32 angle;

    shade = (roll() & 2); self->flag = shade * 0x10;
    item = itemPool;
    angle = measure(self->x, self->y) + 0x800;
    spawn(item, angle);
}
'''


def sources(family, text=SOURCE):
    return [child for found, child in variants(text, 'update') if found == family]


def test_the_result_goes_through_a_dead_local_with_the_address_between():
    expected = SOURCE.replace(
        'item = itemPool;\n    angle = measure(self->x, self->y) + 0x800;',
        'shade = measure(self->x, self->y);\n    item = itemPool;\n    angle = shade + 0x800;')
    assert sources(CARRIER) == [expected]


def test_either_order_of_the_two_statements():
    swapped = SOURCE.replace(
        'item = itemPool;\n    angle = measure(self->x, self->y) + 0x800;',
        'angle = measure(self->x, self->y) + 0x800;\n    item = itemPool;')
    assert 'shade = measure(self->x, self->y);\n    item = itemPool;\n    angle = shade + 0x800;' in sources(
        CARRIER, swapped)[0]


def test_a_local_still_read_is_not_a_carrier():
    assert not sources(CARRIER, SOURCE.replace('spawn(item, angle);', 'spawn(item, angle + shade);'))


def test_a_scratch_value_is_written_into_its_only_use():
    assert sources(INLINE) == [SOURCE.replace('shade = (roll() & 2); self->flag = shade * 0x10;',
                                              'self->flag = (roll() & 2) * 0x10;')]


def test_a_value_read_later_stays():
    assert not sources(INLINE, SOURCE.replace('spawn(item, angle);', 'spawn(item, shade);'))


def test_nothing_inside_a_loop():
    text = SOURCE.replace('{\n    Item *item;', '{\n    Item *item;', 1).replace(
        '    shade = (roll()', '    while (self->flag) {\n    shade = (roll()').replace(
        'spawn(item, angle);\n', 'spawn(item, angle);\n    }\n')
    assert not variants(text, 'update')


def test_registered():
    assert any(CARRIER in entry.families for entry in registry.declared())
