"""Opt-in paid, read-only end-to-end golden tests. No expected answers enter retrieval.

Usage: uv run python tests/run_live_golden.py --questions <private JSON> --output <new private directory>
Question records: {id, question, expected, caution, source_ids}. Run only with authorization.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from bulsae.graphrag.web_server import answer_question


def run_case(case, output):
    try:
        response = answer_question(case['question'])
    except Exception as exc:
        # Never serialize credentials or arbitrary SDK exception payloads.
        response = {'status':'execution_error', 'error_type':type(exc).__name__}
    result = {'golden':case, 'response':response}
    with (output / (case['id'] + '.json')).open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return {'id':case['id'], 'status':response['status'],
            'additional_sections':sum(s.get('section_type') == 'additional' for s in response.get('sections',[]))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cases=json.loads(args.questions.read_text(encoding='utf-8'))
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Questions need unique IDs')
    for case in cases:
        if not case['id'].isalnum() or not isinstance(case['question'],str):
            raise ValueError('Invalid question record')
    args.output.mkdir(parents=True,exist_ok=False)
    print(f'Actual API tests: {len(cases)}; DB reads only',flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run_case,case,args.output) for case in cases]):
            print(json.dumps(future.result(),ensure_ascii=False),flush=True)

if __name__ == '__main__': main()
