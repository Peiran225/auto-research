"""Baseline: a history-independent (open-loop) policy that always plays action 0."""
import json

POLICY = {"": 0, "0:0": 0, "0:1": 0, "1:0": 0, "1:1": 0}

if __name__ == '__main__':
    json.dump({'scenario': 'A', 'horizon': 2, 'p': '1/2', 'policy': POLICY}, open('policy.json', 'w'))
