from decomprepair.label_block_switch import FAMILY, variants

SOURCE = '''void f(void *arg0, s16 tag)
{
    if (tag != 2)
    {
        if (!(tag >= 3))
        {
            if (tag != 0)
            {
            }
            else
            {
                goto block_9;
            }
        }
        else
            if (inline_fn(tag == 4) || (tag == 8))
        {
            goto block_9;
        }
    }
    else
    {
        block_9:
        refresh(arg0);
    }
    done(arg0);
}
'''


def switches(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_tree_that_jumps_to_one_block_becomes_a_switch_over_the_values_that_reach_it():
    texts = switches()
    assert len(texts) == 1
    text = texts[0]
    assert '    switch (tag)\n    {\n      case 0:\n      case 2:\n      case 4:\n      case 8:\n        refresh(arg0);\n' in text
    assert 'goto' not in text and text.rstrip().endswith('done(arg0);\n}'.rstrip())


def test_a_tree_that_does_other_work_or_reads_two_variables_is_left_alone():
    assert not switches(SOURCE.replace('goto block_9;\n            }', 'goto block_9;\n            }\n            other(arg0);', 1))
    assert not switches(SOURCE.replace('tag == 8', 'arg0 == 8'))


def test_an_else_block_whose_braces_never_balance_is_skipped_not_a_crash():
    """The app's draft path died on a 874-instruction function: `block_end` of an `else {` was None and `end + 1` raised."""
    from unittest import mock

    from decomprepair import label_block_switch
    real = label_block_switch.block_end
    calls = []

    def second_is_none(body, index):
        calls.append(index)
        return None if len(calls) > 1 and body[index - 1].stripped == 'else' else real(body, index)

    code = SOURCE.replace('    done(arg0);', '    if (arg0 != 0)\n    {\n        one(arg0);\n    }\n    else\n    {\n        two(arg0);\n    }\n    done(arg0);')
    with mock.patch.object(label_block_switch, 'block_end', second_is_none):
        assert isinstance(variants(code, 'f'), list)
