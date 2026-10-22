#!/usr/bin/env python3
"""Request rollback from its original supervisor; never signal PIDs or touch audio."""
import argparse
from pathlib import Path
import sys
from trial_support import request_return, RollbackError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,required=True)
    args=parser.parse_args()
    try:
        request_return(args.session)
    except FileExistsError:
        print('A return request already exists. Inspect state.json; this is not proof of completion.')
        return 0
    except (OSError,RollbackError) as exc:
        print(str(exc),file=sys.stderr);return 1
    print('Return requested. Wait for state.json verification; the request is not completion.')
    return 0


if __name__=='__main__':sys.exit(main())
