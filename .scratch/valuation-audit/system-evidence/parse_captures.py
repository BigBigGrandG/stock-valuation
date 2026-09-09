import json
from pathlib import Path

DIR = Path('.scratch/valuation-audit/system-evidence')

for ticker in ['AMD', 'META', 'GOOG']:
    val_file = DIR / f'{ticker}-api-valuation.json'
    if not val_file.exists():
        continue
    data = json.loads(val_file.read_text(encoding='utf-8'))
    print(f'=== {ticker} ===')
    print('Price:', data.get('current_price'), 'as of', data.get('as_of'))
    print('Warnings:', data.get('warnings'))
    comp = data.get('composite', {})
    print('Composite: low=', comp.get('low'), 'base=', comp.get('base'), 'high=', comp.get('high'), 'class=', comp.get('classification'), 'mos=', comp.get('margin_of_safety'))
    print('Weights:', comp.get('weights'))
    for m_key, m_val in data.get('valuations', {}).items():
        avail = m_val.get('available')
        base_val = m_val.get('base', {}).get('price_per_share') if m_val.get('base') else None
        reason = m_val.get('unavailable_reason')
        print(f'  Model {m_key}: available={avail}, base={base_val}, reason={reason}')
        if m_key == 'dcf' and avail:
            scenarios = m_val.get('dcf_scenarios', [])
            if scenarios:
                base_s = scenarios[1] if len(scenarios) > 1 else scenarios[0]
                tv = float(base_s.get('terminal_value', 0))
                sum_pv = sum(float(p) for p in base_s.get('pv_projections', []))
                ev = float(base_s.get('enterprise_value', 0))
                pv_tv = float(base_s.get('pv_terminal_value', 0))
                print(f'    DCF Base: EV={ev:,.2f}, sum_pv={sum_pv:,.2f}, TV={tv:,.2f}, pv_tv={pv_tv:,.2f}, TV_ratio={pv_tv/ev if ev else 0:.2%}')
                print('    DCF Projections:', base_s.get('fcff_projections'))
        if m_key == 'ev_ebitda' and avail:
            f_ebitda = m_val.get('input_metrics', {}).get('forward_ebitda', {})
            print('    EV/EBITDA input: ebitda=', f_ebitda.get('value'), 'period=', f_ebitda.get('period'), 'notes=', f_ebitda.get('notes'))
            print('    EV/EBITDA shares=', m_val.get('input_metrics', {}).get('diluted_shares', {}).get('value'), 'net_debt=', m_val.get('input_metrics', {}).get('net_debt', {}).get('value'))
        if m_key == 'fcf_yield' and avail:
            f_fcf = m_val.get('input_metrics', {}).get('forward_fcf', {})
            print('    FCF input: fcf=', f_fcf.get('value'), 'period=', f_fcf.get('period'), 'notes=', f_fcf.get('notes'))
        if m_key == 'forward_pe' and avail:
            f_eps = m_val.get('input_metrics', {}).get('forward_eps', {})
            print('    PE input: eps=', f_eps.get('value'), 'period=', f_eps.get('period'), 'notes=', f_eps.get('notes'))
