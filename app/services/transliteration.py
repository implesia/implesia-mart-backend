"""Readable Latin spelling of Bengali text, used for new product slugs.

A small phonetic scheme (no dependency): consonants carry an inherent "o" unless
a vowel sign, a hasanta or the end of the word follows. "স্মার্ট ঘড়ি" becomes
"smart ghori" instead of the letter-by-letter "smaartt ghddi".
"""

_CONSONANTS = {
    "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "ng",
    "চ": "ch", "ছ": "chh", "জ": "j", "ঝ": "jh", "ঞ": "n",
    "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh", "ণ": "n",
    "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n",
    "প": "p", "ফ": "f", "ব": "b", "ভ": "bh", "ম": "m",
    "য": "j", "র": "r", "ল": "l", "শ": "sh", "ষ": "sh",
    "স": "s", "হ": "h", "\u09dc": "r", "\u09dd": "rh", "\u09df": "y",
}  # fmt: skip
_VOWELS = {
    "অ": "o", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u", "ঊ": "u",
    "ঋ": "ri", "এ": "e", "ঐ": "oi", "ও": "o", "ঔ": "ou",
}  # fmt: skip
_SIGNS = {
    "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u",
    "ৃ": "ri", "ে": "e", "ৈ": "oi", "ো": "o", "ৌ": "ou",
}  # fmt: skip
_MARKS = {"ৎ": "t", "ং": "ng", "ঃ": "h", "ঁ": ""}
_HASANTA = "্"
_NUKTA = "়"
_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# ড়, ঢ় and য় typed as base letter + nukta become the single code point.
_NUKTA_FORMS = {"ড": "\u09dc", "ঢ": "\u09dd", "য": "\u09df"}


def _normalise(text: str) -> str:
    text = text.translate(_DIGITS)
    for base, composed in _NUKTA_FORMS.items():
        text = text.replace(base + _NUKTA, composed)
    return text


def bengali_to_latin(text: str) -> str:
    """Transliterate Bengali letters; every other character passes through."""
    chars = _normalise(text)
    out: list[str] = []
    for index, char in enumerate(chars):
        if char in _CONSONANTS:
            # য after a hasanta (য-ফলা) sounds like "y": ব্যাগ -> byag.
            joined = index > 0 and chars[index - 1] == _HASANTA
            out.append("y" if char == "য" and joined else _CONSONANTS[char])
            following = chars[index + 1] if index + 1 < len(chars) else ""
            if following in _CONSONANTS or following in _MARKS and following != "ঁ":
                out.append("o")
        elif char in _VOWELS:
            out.append(_VOWELS[char])
        elif char in _SIGNS:
            out.append(_SIGNS[char])
        elif char in _MARKS:
            out.append(_MARKS[char])
        elif char in (_HASANTA, _NUKTA, "\u200c", "\u200d"):
            continue
        else:
            out.append(char)
    return "".join(out)
