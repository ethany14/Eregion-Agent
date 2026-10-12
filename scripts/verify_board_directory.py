"""Re-GET verified boards, serial/rate-limited. Dry-run unless --write is given."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime.career.board_directory import DIRECTORY, BoardEntry, load_directory, verify
from agent_runtime.career.discovery import JobDiscovery, board_source


def refresh(entries, discovery, flagged=()):
    updated, report = [], []
    for board in entries[:200]:
        source = board_source(board)
        try:
            fresh = BoardEntry.model_validate(verify(board, discovery)).model_dump(mode='json', exclude_none=True)
            updated.append(fresh)
            report.append({'source':source, 'status':'verified', 'count':fresh['job_count_at_verification'],
                           'verified_at':fresh['verified_at'], 'health_flagged':source in flagged})
        except Exception as exc:
            # Retain original date (never certify an unsuccessful refresh).
            updated.append(board)
            report.append({'source':source, 'status':'refresh_required', 'error':type(exc).__name__,
                           'detail':str(exc), 'health_flagged':source in flagged})
    if len(entries)>200: raise ValueError('Maximum 200 boards per invocation.')
    return updated, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--health', type=Path, help='Exported search_source_health JSON; no task/user content needed.')
    args = parser.parse_args()
    health = json.loads(args.health.read_text(encoding='utf-8')) if args.health else {}
    flagged = [k for k,v in health.get('history', {}).items() if v.get('refresh_required')]
    discovery = JobDiscovery()
    try: updated, report = refresh(load_directory(args.directory), discovery, flagged)
    finally: discovery.close()
    if args.write: args.directory.write_text(json.dumps(updated, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps({'dry_run':not args.write, 'boards':report}, indent=2))
    return int(any(r['status']!='verified' for r in report))


if __name__ == '__main__': raise SystemExit(main())
