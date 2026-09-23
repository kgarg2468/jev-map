"""Small original fixture with direct, indirect, and instance-method behavior."""


def normalize(text):
    return text.strip().lower()


def slugify(text):
    return normalize(text).replace(" ", "-")


def parse_port(text):
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return port


class Cleaner:
    def compact(self, text):
        return " ".join(text.split())
