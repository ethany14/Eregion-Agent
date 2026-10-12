"""Run pytest with inherited Windows workspace ACLs in restricted environments.

Python 3.13 mkdir(mode=0o700) installs an owner-only DACL that excludes the
sandbox identity. Use normal inherited ACLs for test scratch directories only.
Network/config isolation remains owned by tests/conftest.py.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.name == 'nt':
    original_mkdir = os.mkdir
    def inherited_mkdir(path, mode=0o777, *, dir_fd=None):
        return original_mkdir(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)
    os.mkdir = inherited_mkdir

if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main(sys.argv[1:]))
