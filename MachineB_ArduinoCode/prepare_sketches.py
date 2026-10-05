#!/usr/bin/env python3
"""Prepare independent Arduino IDE sketches; avoids compiling both setup() functions together."""
import argparse
from pathlib import Path
import shutil


def prepare(destination):
    source = Path(__file__).resolve().parent
    for board in (1, 2):
        folder = Path(destination) / f'BatteryCartBoard{board}'
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / f'RFID_ARDUINO_{board}.ino', folder / f'BatteryCartBoard{board}.ino')
        shutil.copyfile(source / 'CartProtocol.h', folder / 'CartProtocol.h')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    prepare(parser.parse_args().destination)
