from decomprepair.member_address_respell import FAMILY, REPAIR, variants

SOURCE = """void frame(Task *task)
{
    Work *work;

    work = &task->work;
    start(work);
    if (flag) {
        draw(work);
    }
    flush(work, (u32) end - (u32) work);
    task->list = work->list;
}
"""


def _texts(source=SOURCE):
    return [text for family, text in variants(source, 'frame') if family == FAMILY]


def test_every_read_in_one_statement_is_written_as_the_address():
    found = _texts()
    want = SOURCE.replace('flush(work, (u32) end - (u32) work);',
                          'flush((&task->work), (u32) end - (u32) (&task->work));')
    assert want in found, found
    # one child per statement that reads the local
    assert len(found) == 4
    assert all(text.count('(&task->work)') <= 2 and 'work = &task->work;' in text for text in found)


def test_an_offset_from_the_parameter_is_the_same_shape():
    found = _texts(SOURCE.replace('work = &task->work;', 'work = (Work *) (task + 0x58);'))
    assert any('start(((Work *) (task + 0x58)));' in text for text in found), found


def test_a_reassigned_local_or_parameter_and_a_taken_address_are_left_alone():
    assert _texts(SOURCE.replace('start(work);', 'work++;')) == []
    assert _texts(SOURCE.replace('start(work);', 'task = next(task);')) == []
    assert _texts(SOURCE.replace('start(work);', 'start(&work);')) == []
    assert _texts(SOURCE.replace('work = &task->work;', 'work = &global->work;')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['needs'] == ('source', 'name')
