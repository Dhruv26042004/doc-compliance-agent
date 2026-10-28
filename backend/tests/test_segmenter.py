from app.segmenter import MAX_CHARS, MIN_CHARS, split_text


def test_offsets_index_original_text():
    text = "1. Term.\n\nThis Agreement lasts three years.\n\n\n  2. Governing Law. Delaware law applies.  \n"
    segs = split_text(text)
    assert [text[s.start : s.end] for s in segs] == [
        "This Agreement lasts three years.",
        "2. Governing Law. Delaware law applies.",
    ]  # "1. Term." is under MIN_CHARS


def test_long_paragraph_is_split_at_sentences():
    sentence = "The Supplier shall deliver the Products on time and in full. "
    text = sentence * 100  # ~6000 chars, one paragraph
    segs = split_text(text)
    assert len(segs) > 1
    for s in segs:
        assert MIN_CHARS <= s.end - s.start <= MAX_CHARS
        assert text[s.start : s.end].endswith(".")
    # Pieces are contiguous apart from whitespace.
    for a, b in zip(segs, segs[1:]):
        assert text[a.end : b.start].strip() == ""


def test_long_text_without_sentence_breaks_is_still_bounded():
    text = "word " * 2000
    segs = split_text(text)
    assert all(s.end - s.start <= MAX_CHARS for s in segs)
    assert segs[0].start == 0
