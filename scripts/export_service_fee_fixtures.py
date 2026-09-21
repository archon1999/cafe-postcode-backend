"""Export reviewed formula cases and compiled programs for other runtimes.

Usage: python scripts/export_service_fee_fixtures.py <output.json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.service_fee_formulas.catalog import normalize_definition
from common.tests.service_fee_formula_cases import CASES, CONTEXT


def fixtures():
    return [
        {'name': case['name'], 'definition': normalize_definition({
            'source': case['source'], 'parameters': case.get('parameters', {}),
            'timezone': case.get('timezone', 'Asia/Tashkent'),
        }), 'context': {**CONTEXT, **case.get('context', {})},
         **({'error': True} if case.get('error') else {'amount': case['amount']})}
        for case in CASES
    ]


if __name__ == '__main__':
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(fixtures(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
