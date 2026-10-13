"""Verify candidate public company boards (serial public GETs); dry-run unless --write.

A candidate is added only when its public API answers and at least two data/analytics
titles are observed in the requested location (same verify() as the directory).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from eregion.runtime.career.board_directory import DIRECTORY, BoardEntry, load_directory, verify, location_covered
from eregion.runtime.career.discovery import JobDiscovery, board_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates', type=Path, help='JSON list of {"platform","company"}')
    parser.add_argument('--family', default='data/analytics')
    parser.add_argument('--location', default='New York, NY')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    existing = load_directory()
    known = {board_source(b) for b in existing}
    discovery = JobDiscovery()
    added, report = [], []
    try:
        for row in json.loads(args.candidates.read_text(encoding='utf-8'))[:120]:
            board = {'platform': row['platform'], 'company': row['company'], 'display_name': row['company'],
                     'domains': [], 'locations': [], 'source_url': '', 'verified_at': '2000-01-01',
                     'verified_by': 'public_api_get', 'job_count_at_verification': 0,
                     'notes': 'Added from a verified public API GET for NYC data/analytics coverage.'}
            board['source_url'] = {'greenhouse': f"https://boards.greenhouse.io/{row['company']}",
                                   'lever': f"https://jobs.lever.co/{row['company']}",
                                   'ashby': f"https://jobs.ashbyhq.com/{row['company']}"}[row['platform']]
            if board_source(board) in known:
                report.append({'board': row, 'status': 'already_listed'}); continue
            try:
                fresh = BoardEntry.model_validate(verify(board, discovery)).model_dump(mode='json', exclude_none=True)
            except Exception as exc:
                report.append({'board': row, 'status': 'unavailable', 'error': type(exc).__name__}); continue
            places = fresh.get('family_locations', {}).get(args.family, [])
            covered = [p for p in places if location_covered(args.location, p)]
            if args.family in fresh['domains'] and covered:
                added.append(fresh); known.add(board_source(fresh))
                report.append({'board': row, 'status': 'added', 'jobs': fresh['job_count_at_verification'], 'places': covered[:5]})
            else:
                report.append({'board': row, 'status': 'no_family_in_location', 'jobs': fresh['job_count_at_verification']})
    finally:
        discovery.close()
    if args.write and added:
        DIRECTORY.write_text(json.dumps(existing + added, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'dry_run': not args.write, 'added': len(added), 'report': report}, indent=1))


if __name__ == '__main__':
    main()
