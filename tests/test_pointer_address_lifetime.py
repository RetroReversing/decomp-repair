import pytest

from decomprepair import pointer_address_lifetime as repair

SOURCE = """typedef unsigned int Word;
extern char state[];
extern Word *global_view;
extern Word records[];
void draw(Word *);
void use(void *);
void consume(Word);
void f(void) {
    Word *slot;
    {
        Word *view;
        view = global_view;
        draw(view);
    }
    use((void *)(*((void **) (state + 16))));
#ifdef PORT
    consume(1);
#else
    consume(2);
#endif
    slot = &records[0];
    consume(*slot);
}
"""


def test_fixed_address_spans_call_but_load_stays_in_place():
    assert repair.variants(SOURCE, 'f') == [(repair.FAMILY, SOURCE.replace(
        '        view = global_view;', '        slot = (void *)(state + 16);\n        view = global_view;'
    ).replace('use((void *)(*((void **) (state + 16))));', 'use(*(void **)slot);'))]


@pytest.mark.parametrize('source', [
    SOURCE.replace('draw(view);', 'draw(view);\n        consume(*slot);'),
    SOURCE.replace('consume(2);', 'consume(*slot);'),
    SOURCE.replace('slot = &records[0];', 'if (records[0]) slot = &records[0];'),
    SOURCE.replace('    {\n', '    register_escape(&slot);\n    {\n', 1),
    '#define ESCAPE(x) register_escape(&(x))\n' + SOURCE.replace('    {\n', '    ESCAPE(slot);\n    {\n', 1),
    '#define BYPASS goto after\n' + SOURCE.replace('draw(view);','BYPASS;\n        draw(view);'),
    SOURCE.replace('        view = global_view;', '        if (records[0])\n            view = global_view;'),
    SOURCE.replace('    use((void *)', 'after:\n    use((void *)').replace('draw(view);', 'draw(view);\n        if (records[0]) goto after;'),
    SOURCE.replace('        view = global_view;', '        goto draw_label;\n        view = global_view;\n    draw_label:'),
    SOURCE.replace('    use((void *)', '    char *state = (char *)records;\n    use((void *)'),
    SOURCE.replace('    Word *slot;', '    const Word *slot;'),
    SOURCE.replace('state + 16', 'state + records[0]'),
    SOURCE.replace('(*((void **) (state + 16)))', '(*(void **)state + 16)'),
    SOURCE.replace('#ifdef PORT', '#if VERSION > 1'),
])
def test_unproven_lifetimes_produce_no_candidate(source):
    assert not repair.variants(source, 'f')
