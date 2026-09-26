from __future__ import annotations

from schema import utf8_len

from planning.prompt_budget import fit_to_bytes, normalize_punctuation

EM_DASH = chr(0x2014)

# The real shot_008 prompt fal rejected at 2069 bytes (run p_f80886).
SHOT_008 = (
    "Animated. Establishing wide shot, camera at mid-height slowly pushing in through a broken "
    "archway. Setting: an ancient crumbling hilltop fortress of weathered tan sandstone, with "
    "collapsed ramparts, broken archways, and a half-fallen watchtower overlooking the valley. "
    "Rubble and dry weeds fill the courtyard, faded carvings mark the eroded walls, and empty "
    "window slits gape toward the mountains. Standing stark against a bruised twilight sky. Long "
    "dramatic shadows and cool dusk light. A lean man in his late thirties, 6ft tall, with "
    "weathered olive skin, a short dark stubble beard, sharp grey-green eyes, and close-cropped "
    "black hair flecked with grey at the temples. A thin white scar cuts through his left eyebrow. "
    "He wears a sand-brown wool field jacket over a dust-stained grey shirt, dark canvas cargo "
    "trousers, worn tan leather boots, and a faded checkered keffiyeh loosely wrapped around his "
    f"neck. A battered leather satchel is slung across his chest {EM_DASH} Kaverin steps into the "
    "ruined fort courtyard and stops dead. Ahead in the shadows stand two figures: a "
    "broad-shouldered man in his mid-forties, 5ft11in, with pale skin, slicked-back "
    "salt-and-pepper hair, a trimmed grey goatee, and cold pale-blue eyes framed by rimless "
    "glasses. He wears a charcoal tactical vest over a black long-sleeve shirt, dark trousers, and "
    "fingerless gloves, with a silver watch on his left wrist. His expression is calm and "
    f"unreadable, a faint controlled smile {EM_DASH} Darius. Beside him, a tall imposing man in his "
    "fifties, 6ft2in, with dark tanned skin, a full greying black beard, heavy brows, and a hard "
    "lined face with a hooked nose. He wears a mud-brown military-surplus coat over a dark tunic, "
    "an ammunition bandolier across his chest, a black wool cap, and heavy scuffed boots. A worn "
    f"rifle is slung on his back. He carries himself with menacing stillness {EM_DASH} Commander Rahim. "
    "Both wait in the shadows, watching Kaverin. Rendered in a painterly semi-realistic 2D "
    "animation style with hand-drawn linework, muted earth-toned palette, soft cel shading, and "
    "subtle grain texture."
)

STYLE_SENTENCE = (
    "Rendered in a painterly semi-realistic 2D animation style with hand-drawn linework, muted "
    "earth-toned palette, soft cel shading, and subtle grain texture."
)


def test_fixture_is_the_rejected_size():
    assert utf8_len(SHOT_008) == 2069


def test_fit_keeps_first_and_style_sentences():
    fitted = fit_to_bytes(SHOT_008, 2048)
    assert utf8_len(fitted) == 2025
    assert fitted.startswith("Animated. Establishing wide shot")
    assert fitted.endswith(STYLE_SENTENCE)
    assert "Both wait in the shadows, watching Kaverin." not in fitted
    assert fitted == SHOT_008.replace("Both wait in the shadows, watching Kaverin. ", "")


def test_fit_leaves_short_text_and_no_limit_alone():
    assert fit_to_bytes("A short prompt.", 2048) == "A short prompt."
    assert fit_to_bytes(SHOT_008, None) == SHOT_008


def test_fit_drops_middle_sentences_from_the_end():
    text = "First. Middle one. Middle two. Last."
    assert fit_to_bytes(text, len("First. Middle one. Last.")) == "First. Middle one. Last."
    assert fit_to_bytes(text, len("First. Last.")) == "First. Last."


def test_fit_last_resort_cut_never_splits_a_multibyte_character():
    text = ("word" + EM_DASH) * 200
    fitted = fit_to_bytes(text, 101)
    assert utf8_len(fitted) <= 101
    fitted.encode("utf-8").decode("utf-8")
    assert fitted and text.startswith(fitted)


def test_fit_last_resort_cuts_at_a_space():
    fitted = fit_to_bytes("alpha beta gamma delta", 13)
    assert fitted == "alpha beta"


def test_normalize_punctuation_maps_to_ascii():
    text = (
        f"a{EM_DASH}b{chr(0x2013)}c {chr(0x2018)}q{chr(0x2019)} {chr(0x201c)}d{chr(0x201d)}"
        f"{chr(0x2026)}{chr(0x00a0)}e"
    )
    assert normalize_punctuation(text) == "a-b-c 'q' \"d\"... e"
    assert utf8_len(normalize_punctuation(SHOT_008)) == 2069 - 3 * 2
