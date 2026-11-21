from decomprepair.mutable_parameter_local import variants


def test_splits_reassigned_pointer_without_rewriting_body_uses():
    source = """int walk(void *room, void *unused) {
    int found = 0;
    void *next;
    while (room) {
        next = advance(room);
        room = next;
    }
    return found;
}"""
    generated = [candidate for _, candidate in variants(source, 'walk')]
    assert generated
    assert all('void *roomInput, void *unused' in candidate for candidate in generated)
    assert all('void * room = roomInput;' in candidate for candidate in generated)
    assert all('next = advance(room);\n        room = next;' in candidate for candidate in generated)
    assert not variants(source.replace('advance(room)', 'advance(&room)'), 'walk')
    assert not variants(source.replace('room = next;', 'next = room;'), 'walk')
