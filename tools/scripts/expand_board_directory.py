"""Add candidate company boards to the directory only when their public API verifies them.

Each candidate token is tried on the public Greenhouse, Lever and Ashby job-board APIs (GET,
serial, rate-limited by JobDiscovery). A board is kept only when the API answers with at
least one listed job; its role families and locations come from the live listing
(board_directory.verify), never from the candidate list. Dry run unless --write is given.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from eregion.runtime.career.board_directory import DIRECTORY, BoardEntry, load_directory, verify
from eregion.runtime.career.discovery import JobDiscovery, board_source

PAGES = {'greenhouse': 'https://job-boards.greenhouse.io/{}', 'lever': 'https://jobs.lever.co/{}',
         'ashby': 'https://jobs.ashbyhq.com/{}'}


def candidate(platform, token, name):
    return {'platform': platform, 'company': token, 'display_name': name, 'domains': [], 'locations': [],
            'source_url': PAGES[platform].format(token), 'verified_at': '2000-01-01', 'verified_by': 'public_api_get',
            'job_count_at_verification': 0,
            'notes': 'Added by expand_board_directory after a public API GET returned listed jobs.'}


def expand(candidates, discovery, existing):
    known = {board_source(b) for b in existing}
    added, report = [], []
    for row in candidates[:150]:
        token, name = row['token'], row.get('name') or row['token']
        outcome = {'token': token, 'status': 'not_found'}
        for platform in row.get('platforms') or ('greenhouse', 'lever', 'ashby'):
            board = candidate(platform, token, name)
            if board_source(board) in known:
                outcome = {'token': token, 'status': 'already_listed', 'source': board_source(board)}
                break
            try:
                fresh = BoardEntry.model_validate(verify(board, discovery)).model_dump(mode='json', exclude_none=True)
            except Exception as exc:
                outcome.setdefault('tried', []).append(f'{platform}:{type(exc).__name__}')
                continue
            if fresh['job_count_at_verification'] <= 0:
                outcome = {'token': token, 'status': 'empty', 'source': board_source(fresh)}
                break
            added.append(fresh); known.add(board_source(fresh))
            outcome = {'token': token, 'status': 'verified', 'source': board_source(fresh),
                       'jobs': fresh['job_count_at_verification'], 'domains': fresh['domains'],
                       'data_analytics_ny': [p for p in (fresh.get('family_locations') or {}).get('data/analytics', [])
                                             if 'new york' in p.casefold() or 'nyc' in p.casefold()][:5]}
            break
        report.append(outcome)
    return added, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates', type=Path, help='JSON list of {"token", "name", optional "platforms"}')
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    existing = load_directory(args.directory)
    discovery = JobDiscovery()
    try:
        added, report = expand(json.loads(args.candidates.read_text(encoding='utf-8')), discovery, existing)
    finally:
        discovery.close()
    summary = {'verified': len(added), 'checked': len(report), 'report': report}
    if args.report:
        args.report.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'report'}))
    if args.write and added:
        args.directory.write_text(json.dumps(existing + added, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        load_directory(args.directory)   # re-validate the written file


if __name__ == '__main__':
    main()
