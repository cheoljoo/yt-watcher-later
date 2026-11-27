"""태양광 발전 사업 수익 모델 (세전, 연 단위). newbiz_solar.py 의 표·그래프와 페이지의 계산기(JS)가 같은 식을 쓴다.
단위: 금액 만원, 가격 원/kWh."""

BASE = dict(kw=100, unit=130, grid=1100, hours=3.6, degr=0.5, price=147, om=350, om_up=2.0, rent=0, loan=80, rate=1.75, grace=5, repay=10, years=20)


def simulate(**kw):
    p = {**BASE, **kw}
    invest = p["kw"] * p["unit"] + p["grid"]
    loan = invest * p["loan"] / 100
    equity = invest - loan
    bal, principal = loan, loan / p["repay"] if p["repay"] else 0
    rows = []
    for y in range(1, p["years"] + 1):
        gen = p["kw"] * p["hours"] * 365 * (1 - p["degr"] / 100) ** (y - 1)          # kWh
        rev = gen * p["price"] / 10000
        cost = p["om"] * (1 + p["om_up"] / 100) ** (y - 1) + p["rent"]
        interest = bal * p["rate"] / 100
        pay = min(principal, bal) if y > p["grace"] else 0
        if y == p["grace"] + p["repay"]: pay = bal
        bal -= pay
        rows.append(dict(y=y, gen=gen, rev=rev, op=rev - cost, debt=interest + pay, cf=rev - cost - interest - pay, interest=interest))
    return dict(invest=invest, loan=loan, equity=equity, rows=rows, **metrics(invest, equity, rows))


def irr(flows):
    lo, hi = -0.99, 1.0
    npv = lambda r: sum(f / (1 + r) ** i for i, f in enumerate(flows))
    if npv(lo) * npv(hi) > 0: return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0: hi = mid
        else: lo = mid
    return mid * 100


def payback(start, flows):
    """누적 현금흐름이 0 이상이 되는 시점(년, 보간). 기간 안에 못 하면 None."""
    acc = -start
    for i, f in enumerate(flows, 1):
        if acc + f >= 0 and f > 0: return i - 1 + (-acc) / f
        acc += f
    return None


def metrics(invest, equity, rows):
    op, cf = [r["op"] for r in rows], [r["cf"] for r in rows]
    debt = [r for r in rows if r["debt"] > 0]
    return dict(rev1=rows[0]["rev"], op1=rows[0]["op"], yield1=rows[0]["op"] / invest * 100,
                payback=payback(invest, op), eq_payback=payback(equity, cf),
                profit=sum(op) - invest - sum(r["interest"] for r in rows),
                roi=(sum(op) - invest - sum(r["interest"] for r in rows)) / invest * 100,
                irr=irr([-invest] + op), eq_irr=irr([-equity] + cf) if equity > 0 else None,
                min_cf=min(cf), dscr=min((r["op"] / r["debt"] for r in debt), default=None))


SCENARIOS = [("우대 포함 163원", dict(price=163)), ("기준 147원", dict(price=147)), ("하락 130원", dict(price=130)), ("비관 110원", dict(price=110))]
