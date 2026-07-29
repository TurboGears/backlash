"""backlash is dependency-free: it must import with the stdlib only.

This keeps the package trivial to vendor and prevents any middleware
module from quietly growing a runtime dependency.
"""
import subprocess
import sys
from os.path import join, dirname


def test_backlash_imports_with_stdlib_only():
    # Subprocess: sibling tests already imported backlash (and pytest pulls
    # in third-party modules), so only a fresh interpreter gives an honest
    # view of what importing backlash loads.
    subprocess.run([sys.executable, '-c', (
        'import sys\n'
        'before = set(sys.modules)\n'
        'import backlash, backlash.asgi, backlash.wsgi, backlash.debug\n'
        'loaded = {m.split(".")[0] for m in set(sys.modules) - before}\n'
        'external = loaded - set(sys.stdlib_module_names) - {"backlash"}\n'
        'assert not external, "non-stdlib imports: %s" % external\n'
    )], check=True, cwd=join(dirname(__file__), '..'))
