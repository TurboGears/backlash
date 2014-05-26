import sys
from .tbtools import Traceback, Frame


class DumpThread(Exception):
    pass


def get_thread_stack(thread_id, description='', context=None):
    e = DumpThread(description)
    tb = Traceback(DumpThread, e, [], context=context)

    f = sys._current_frames()[thread_id]
    n = 0
    while f is not None:
        tb.frames.insert(0, Frame(DumpThread, e, f, context))
        f = f.f_back
        n += 1

    return tb
