"""Let langchain-core's blockbuster guard ignore the profiler's own file checks.

langchain-core's unit-test conftest enables `blockbuster` for every test, which
raises when `os.stat` and similar run inside an event loop. The profiler's
`source_path` helper resolves filenames from inside the profile callback, so
blockbuster would blame the test. Only that helper is allow-listed; every other
blocking-call check stays as the project configured it. Loaded for LangChain
only, via its declared pytest arguments; a no-op when no profiler runs.
"""

from blockbuster import blockbuster as _bb

_ALLOWED = [("popular_profile.py", {"source_path"}), ("full_suite_profile.py", {"source_path"})]
_original_init = _bb.BlockBuster.__init__


def _init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    for function in self.functions.values():
        for allowed in _ALLOWED:
            function.can_block_in(*allowed)


_bb.BlockBuster.__init__ = _init
