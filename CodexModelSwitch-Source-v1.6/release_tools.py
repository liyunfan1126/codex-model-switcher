"""Allowlisted release staging. Never reads LOCALAPPDATA or user credentials."""
import argparse
from pathlib import Path
import shutil
import zipfile

APP_FILES = ['app.py', 'core.py', 'connections.py', 'diagnostics.py', 'catalog.json']
SOURCE_FILES = ['source/' + x for x in APP_FILES] + [
    'source/requirements.txt', 'source/test_core.py', 'source/test_connections.py',
    'source/test_diagnostics.py', 'source/test_platforms.py', 'source/test_cards_ui.py',
    'build.ps1', 'release_tools.py', 'installer/setup.nsi', '使用说明.md', '源码构建说明.md', '测试说明.md', '发布校验说明.md']

def checked(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError('Release input missing or outside source directory: ' + relative)
    return p

def stage(root, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError('Staging directory must be empty to prevent accidental inclusion.')
    output.mkdir(parents=True, exist_ok=True)
    for name in APP_FILES:
        shutil.copyfile(checked(root, 'source/' + name), output / name)

def source_zip(root, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in SOURCE_FILES:
            archive.write(checked(root, name), 'CodexModelSwitch-Source-v1.6/' + name)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['stage', 'source'])
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    (stage if a.action == 'stage' else source_zip)(a.root, a.output)
