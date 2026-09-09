"""Read only this Codex session's latest reported rate limits; never credentials."""
import json
import os
from pathlib import Path

home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
thread_id = os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID')
paths = list((home / 'sessions').rglob(f'*{thread_id}*.jsonl')) if thread_id else []
latest = None
latest_five_hour = None
for path in paths:
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            payload = event.get('payload', {})
            if event.get('type') == 'event_msg' and payload.get('type') == 'token_count' and payload.get('rate_limits'):
                latest = {'timestamp': event.get('timestamp'), 'rate_limits': payload['rate_limits']}
                for bucket in payload['rate_limits'].values():
                    if isinstance(bucket, dict) and bucket.get('window_minutes') == 300:
                        latest_five_hour = {'timestamp': event.get('timestamp'), 'limit_id': payload['rate_limits'].get('limit_id'), **bucket}
result = {'latest': latest, 'remaining_5h_percent': None, 'stop_required': None}
if latest_five_hour:
    remaining = 100 - latest_five_hour['used_percent']
    result.update(five_hour=latest_five_hour, remaining_5h_percent=remaining, stop_required=remaining < 5)
print(json.dumps(result, ensure_ascii=False, indent=2))
