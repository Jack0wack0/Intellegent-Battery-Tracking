#!/usr/bin/env python3
"""One bounded ingestion run; systemd owns the ten-minute schedule."""
from main import main

if __name__ == '__main__':
    main()  # Errors propagate as a nonzero service result; unfinished revisions retry next run.
