def word_count(text: str) -> int:
    return len(text.split(" "))


def average_word_length(text: str) -> float:
    words = text.split()
    return sum(len(w) for w in words) / len(words) if words else 0.0
