import unittest

from text_ops import Cleaner, normalize, parse_port, slugify


class TextTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize(" HELLO "), "hello")

    def test_slugify(self):
        self.assertEqual(slugify(" Hello World "), "hello-world")

    def test_port(self):
        self.assertEqual(parse_port("8080"), 8080)

    def test_port_invalid(self):
        with self.assertRaises(ValueError):
            parse_port("0")

    def test_compact(self):
        cleaner = Cleaner()
        self.assertEqual(cleaner.compact("too   much space"), "too much space")
