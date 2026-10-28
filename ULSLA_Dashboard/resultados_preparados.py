"""Resultados derivados persistentes; nunca modifica os dados de origem."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import tempfile

SCHEMA = 1


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, 'item'):
        return clean(value.item())
    return value


def digest(value):
    raw = json.dumps(clean(value), sort_keys=True, ensure_ascii=False,
                     separators=(',', ':'), allow_nan=False).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def file_signatures(root, names):
    result = []
    for name in sorted(set(names)):
        path = Path(root) / name
        if path.is_file():
            stat = path.stat()
            result.append((name, stat.st_size, stat.st_mtime_ns))
        else:
            result.append((name, None, None))
    return result


def core_history(data, period):
    year, month = map(int, period.split('-'))
    # Série mensal N/N-1 e ponto homólogo N-2.
    keys = {f'{y}-{m:02d}' for y in (year-1, year) for m in range(1, month+1)}
    keys.add(f'{year-2}-{month:02d}')
    return {key: data[key] for key in sorted(keys) if key in data}


def path_for(root, period, block):
    if block not in ('executivo', 'divida', 'pmp'):
        raise ValueError('Bloco desconhecido')
    parts = period.split('-')
    if len(parts) != 2 or len(parts[0]) != 4 or not parts[0].isdigit() or not parts[1].isdigit() or not 1 <= int(parts[1]) <= 12:
        raise ValueError('Período inválido')
    return Path(root) / 'resultados_preparados' / period / f'{block}.json'


def read(root, period, block, signature):
    try:
        obj = json.loads(path_for(root, period, block).read_text(encoding='utf8'))
        if (obj['schema'] == SCHEMA and obj['signature'] == signature
                and obj['period'] == period and obj['block'] == block
                and obj['checksum'] == digest(obj['result'])):
            return obj
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def write(root, period, block, signature, result):
    result = clean(result)
    obj = {'schema': SCHEMA, 'period': period, 'block': block,
           'signature': signature, 'prepared_at': datetime.now(timezone.utc).isoformat(),
           'checksum': digest(result), 'result': result}
    path = path_for(root, period, block)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.preparar_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as out:
            json.dump(obj, out, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return obj
