# Readability: Test setup: document the contract this file protects.
from __future__ import print_function

import os
import runpy
import subprocess
import sys


# Section: run the repo root workflow with clear inputs and outputs.
def _repo_root():
    # Return the prepared result to the caller.
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# Section: run the python3 candidates workflow with clear inputs and outputs.
def _python3_candidates():
    root = _repo_root()
    candidates = []
    env_python = os.environ.get('CASM_TEST_PYTHON3')
    if env_python:
        # Trigger the side effect required for this stage.
        candidates.append(env_python)
    # Trigger the side effect required for this stage.
    candidates.extend([
        os.path.join(root, '.venv', 'Scripts', 'python.exe'),
        os.path.join(root, 'venv', 'Scripts', 'python.exe'),
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python311', 'python.exe'),
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python310', 'python.exe'),
    ])
    return candidates


# Section: run the find python3 workflow with clear inputs and outputs.
def _find_python3():
    # Process each item in this collection using the same rule set.
    for candidate in _python3_candidates():
        # Choose the correct branch before the workflow continues.
        if candidate and os.path.exists(candidate):
            # Return the prepared result to the caller.
            return candidate
    return ''


# Section: run the main workflow with clear inputs and outputs.
def main():
    impl = os.path.join(
        os.path.dirname(__file__),
        'deployed_frontend_navigation_timezone_action_test_impl.py',
    )
    # Choose the correct branch before the workflow continues.
    if sys.version_info[0] >= 3:
        # Prepare values needed by the next step.
        sys.argv[0] = impl
        runpy.run_path(impl, run_name='__main__')
        return 0

    python3 = _find_python3()
    if not python3:
        print('FAIL: Python 3 is required. Set CASM_TEST_PYTHON3 or run with .venv\\Scripts\\python.exe.')
        return 2

    # Return the prepared result to the caller.
    return subprocess.call([python3, impl] + sys.argv[1:])


# Choose the correct branch before the workflow continues.
if __name__ == '__main__':
    sys.exit(main())
