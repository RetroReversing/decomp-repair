from decomprepair import registry
from decomprepair.branch_copy_zero_chain import FAMILY, variants

SOURCE = '''void update(Thing *self) {
    Thing *other;
    s32 level;
    s32 value;

    value = self->shade;
    other = self->partner;
    self->scale += 3;
    level = value - 1;
    value = level;
    self->shade = value;
    if (other != NULL) {
        other->shade = value;
        other->green = 0;
        other->blue = 0;
    }
    if (level >= 9) {
        value = measure(self);
        use(value);
    }
}
'''


def sources(text=SOURCE):
    return [child for family, child in variants(text, 'update') if family == FAMILY]


def test_zero_goes_through_the_copy_and_its_source_rises_together():
    combined = SOURCE.replace('    self->scale += 3;\n    level = value - 1;\n',
                              '    level = value - 1;\n    self->scale += 3;\n').replace(
        'other->green = 0;', 'other->green = value = 0;')
    chain = SOURCE.replace('other->green = 0;', 'other->green = value = 0;')
    assert sources()[0] == combined
    assert chain in sources()


def test_the_source_does_not_rise_above_a_write_of_its_operand():
    text = SOURCE.replace('self->scale += 3;', 'value += 3;').replace('    other = self->partner;\n',
                                                                      '    value = other_value;\n')
    assert all('level = value - 1;\n    value += 3;' not in child for child in sources(text))
    assert sources(text)


def test_nothing_when_the_copy_is_read_after_the_block():
    assert not sources(SOURCE.replace('value = measure(self);', 'use(value);'))


def test_nothing_when_the_source_is_not_read_after_the_block():
    assert not sources(SOURCE.replace('if (level >= 9) {', 'if (self->scale >= 9) {'))


def test_nothing_inside_a_loop():
    text = SOURCE.replace('    value = self->shade;\n', '    while (self->scale) {\n    value = self->shade;\n').replace(
        '        use(value);\n    }\n', '        use(value);\n    }\n    }\n')
    assert not sources(text)


def test_registered():
    assert any(FAMILY in entry.families for entry in registry.declared())
