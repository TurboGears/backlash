import sys
from .tbtools import Traceback, Frame


class DumpThread(Exception):
    backlash_event = True


def get_thread_stack(thread_id, description='', error_type=DumpThread, context=None):
    if isinstance(error_type, str):
        error_type = type(error_type, (DumpThread,), {})
        # Hack to prevent traceback module from printing
        # backlash.frtools.ExceptionName instead of just ExceptionName
        error_type.__module__ = '__main__'

    e = error_type(description)
    tb = Traceback(error_type, e, [], context=context)

    f = sys._current_frames()[thread_id]
    n = 0
    while f is not None:
        tb.frames.insert(0, Frame(error_type, e, f, context))
        f = f.f_back
        n += 1

    return tb
