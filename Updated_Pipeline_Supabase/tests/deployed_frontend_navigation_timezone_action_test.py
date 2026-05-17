from __future__ import print_function

import os
import runpy
import subprocess
import sys


def _repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _python3_candidates():
    root = _repo_root()
    candidates = []
    env_python = os.environ.get('CASM_TEST_PYTHON3')
    if env_python:
        candidates.append(env_python)
    candidates.extend([
        os.path.join(root, '.venv', 'Scripts', 'python.exe'),
        os.path.join(root, 'venv', 'Scripts', 'python.exe'),
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python311', 'python.exe'),
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python310', 'python.exe'),
    ])
    return candidates


def _find_python3():
    for candidate in _python3_candidates():
        if candidate and os.path.exists(candidate):
            return candidate
    return ''


def main():
    impl = os.path.join(
        os.path.dirname(__file__),
        'deployed_frontend_navigation_timezone_action_test_impl.py',
    )
    if sys.version_info[0] >= 3:
        sys.argv[0] = impl
        runpy.run_path(impl, run_name='__main__')
        return 0

    python3 = _find_python3()
    if not python3:
        print('FAIL: Python 3 is required. Set CASM_TEST_PYTHON3 or run with .venv\\Scripts\\python.exe.')
        return 2

    return subprocess.call([python3, impl] + sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
