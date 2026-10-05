"""Atomic artifact publication with hash verification and path containment."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_path(directory, name):
    root = Path(directory).resolve()
    if Path(name).name != name or name in ('.', '..') or '\\' in name:
        raise ValueError('Artifact name must be a single filename')
    path = root / name
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError('Artifact escapes storage root')
    return path


@contextmanager
def atomic_output(path, mode='w', **kwargs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Refusing symlink output')
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.part', dir=path.parent)
    try:
        with os.fdopen(fd, mode, **kwargs) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def copy_verified(source, destination):
    expected = digest(source)
    with atomic_output(destination, 'w+b') as output, open(source, 'rb') as input_file:
        shutil.copyfileobj(input_file, output)
        output.flush()
        output.seek(0)
        checksum = hashlib.sha256()
        for chunk in iter(lambda: output.read(1024 * 1024), b''):
            checksum.update(chunk)
        if checksum.hexdigest() != expected:
            raise OSError('Temporary copy checksum mismatch; previous output preserved')
    if expected != digest(destination):
        raise OSError('Artifact checksum mismatch')
