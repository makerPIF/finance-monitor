# -*- coding: utf-8 -*-
"""
금융 공공데이터 일일 수집 프로그램
  - 한국은행 ECOS Open API  : 금리·환율·주가·물가·은행 수신/대출금리, 100대 통계지표
  - 금융감독원 FINLIFE API   : 은행권 정기예금·적금·주담대·전세대출·신용대출 상품 공시

실행 결과
  data/fin_data.js      -> 두 HTML(dashboard.html, bank_compare.html)이 읽는 데이터
  data/history.json     -> 날짜별 은행 최고금리 이력(매일 실행할수록 쌓임)
  data/snapshots/*.json -> 날짜별 상품 원본 스냅샷

사용법
  python fin_update.py              # 실데이터 수집 (config.json 또는 환경변수의 API 키 사용)
  python fin_update.py --demo       # API 키 없이 화면 확인용 가상 데이터 생성
  python fin_update.py --check      # API 키·통계코드 연결 점검만

표준 라이브러리만 사용합니다(별도 설치 불필요, Python 3.8 이상).
"""
import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
SNAP = os.path.join(DATA, "snapshots")
CONFIG_PATH = os.path.join(BASE, "config.json")

# ---------------------------------------------------------------------------
# ECOS 통계 목록 (필요하면 여기서 추가/수정)
#   key: (표시이름, 그룹, 단위, 통계표코드, 주기, 항목코드, 조회기간(일 or 월))
#   통계표·항목 코드는 ECOS > 개발명세서 > 통계코드검색에서 확인할 수 있습니다.
# ---------------------------------------------------------------------------
ECOS_SERIES = {
    "base_rate": ("한국은행 기준금리", "rate", "%", "722Y001", "D", "0101000", 1100),
    "call":      ("콜금리(1일)",       "rate", "%", "817Y002", "D", "010101000", 1100),
    "cd91":      ("CD(91일)",          "rate", "%", "817Y002", "D", "010502000", 1100),
    "ktb3":      ("국고채(3년)",       "rate", "%", "817Y002", "D", "010200000", 1100),
    "ktb10":     ("국고채(10년)",      "rate", "%", "817Y002", "D", "010210000", 1100),
    "corp3":     ("회사채(3년, AA-)",  "rate", "%", "817Y002", "D", "010300000", 1100),
    "usdkrw":    ("원/달러",           "fx",   "원", "731Y001", "D", "0000001", 1100),
    "jpykrw":    ("원/100엔",          "fx",   "원", "731Y001", "D", "0000002", 1100),
    "eurkrw":    ("원/유로",           "fx",   "원", "731Y001", "D", "0000003", 1100),
    "kospi":     ("KOSPI",             "stock", "pt", "802Y001", "D", "0001000", 1100),
    "kosdaq":    ("KOSDAQ",            "stock", "pt", "802Y001", "D", "0089000", 1100),
    "cpi":       ("소비자물가지수",    "price", "2020=100", "901Y009", "M", "0", 132),
    "dep_rate":  ("예금은행 저축성수신금리(신규)", "bank", "%", "121Y002", "M", "BEABAA2", 132),
    "loan_rate": ("예금은행 대출금리(신규)",       "bank", "%", "121Y006", "M", "BECBLA01", 132),
}

FINLIFE_TYPES = {
    "deposit":  "depositProductsSearch",
    "saving":   "savingProductsSearch",
    "mortgage": "mortgageLoanProductsSearch",
    "rent":     "rentHouseLoanProductsSearch",
    "credit":   "creditLoanProductsSearch",
}
BANK_GROUP = "020000"  # 은행권


# ---------------------------------------------------------------------------
def log(*a):
    print("[%s]" % datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def load_config():
    cfg = {"ecos_key": os.environ.get("ECOS_API_KEY", ""),
           "finlife_key": os.environ.get("FINLIFE_API_KEY", "")}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            file_cfg = json.load(f)
        for k, v in file_cfg.items():
            if v and not str(v).startswith("여기에"):
                cfg[k] = v
    return cfg


def http_json(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 fin-monitor"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 네트워크 일시 오류 재시도
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# ECOS
# ---------------------------------------------------------------------------
def ecos_period(cycle, back):
    today = date.today()
    if cycle == "D":
        return (today - timedelta(days=back)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    if cycle == "M":
        y, m = today.year, today.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        return "%04d%02d" % (y, m), today.strftime("%Y%m")
    raise ValueError(cycle)


def ecos_fmt_date(t):
    if len(t) == 8:
        return "%s-%s-%s" % (t[:4], t[4:6], t[6:])
    if len(t) == 6:
        return "%s-%s" % (t[:4], t[4:])
    return t


def fetch_ecos_series(key, spec):
    name, group, unit, code, cycle, item, back = spec
    start, end = ecos_period(cycle, back)
    url = "https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10000/%s/%s/%s/%s/%s" % (
        key, code, cycle, start, end, item)
    js = http_json(url)
    if "StatisticSearch" not in js:
        msg = js.get("RESULT", {}).get("MESSAGE", str(js)[:120])
        raise RuntimeError(msg)
    pts = []
    for row in js["StatisticSearch"].get("row", []):
        v = num(row.get("DATA_VALUE"))
        if v is not None:
            pts.append([ecos_fmt_date(row["TIME"]), v])
    pts.sort()
    return {"name": name, "group": group, "unit": unit, "cycle": cycle, "points": pts}


def fetch_ecos_keystats(key):
    url = "https://ecos.bok.or.kr/api/KeyStatisticList/%s/json/kr/1/120" % key
    js = http_json(url)
    rows = js.get("KeyStatisticList", {}).get("row", [])
    out = []
    for r in rows:
        out.append({"cls": r.get("CLASS_NAME", ""), "name": r.get("KEYSTAT_NAME", ""),
                    "value": num(r.get("DATA_VALUE")), "unit": r.get("UNIT_NAME", ""),
                    "cycle": r.get("CYCLE", "")})
    return out


# ---------------------------------------------------------------------------
# FINLIFE (금융상품통합비교공시)
# ---------------------------------------------------------------------------
def fetch_finlife_raw(key, api):
    base, opts, page, maxp = [], [], 1, 1
    while page <= maxp:
        q = urllib.parse.urlencode({"auth": key, "topFinGrpNo": BANK_GROUP, "pageNo": page})
        js = http_json("https://finlife.fss.or.kr/finlifeapi/%s.json?%s" % (api, q))
        res = js.get("result", {})
        if res.get("err_cd") not in ("000", None):
            raise RuntimeError("%s %s" % (res.get("err_cd"), res.get("err_msg")))
        base += res.get("baseList", []) or []
        opts += res.get("optionList", []) or []
        maxp = int(res.get("max_page_no") or 1)
        page += 1
    return base, opts


def _key(r, extra=None):
    k = (r.get("fin_co_no"), r.get("fin_prdt_cd"))
    return k + ((r.get(extra),) if extra else ())


def normalize(kind, base, opts):
    extra = "crdt_prdt_type" if kind == "credit" else None
    idx = {}
    for b in base:
        p = {"bank": b.get("kor_co_nm", "").strip(), "code": b.get("fin_prdt_cd"),
             "name": b.get("fin_prdt_nm", "").strip(), "joinWay": b.get("join_way") or "",
             "month": b.get("dcls_month"), "options": []}
        if kind in ("deposit", "saving"):
            p.update(special=b.get("spcl_cnd") or "", member=b.get("join_member") or "",
                     maturity=b.get("mtrt_int") or "", note=b.get("etc_note") or "",
                     limit=b.get("max_limit"), deny=b.get("join_deny"))
        elif kind in ("mortgage", "rent"):
            p.update(cost=b.get("loan_inci_expn") or "", earlyFee=b.get("erly_rpay_fee") or "",
                     delay=b.get("dly_rate") or "", limitTxt=b.get("loan_lmt") or "")
        else:
            p.update(type=b.get("crdt_prdt_type_nm") or "", cb=b.get("cb_name") or "")
        idx[_key(b, extra)] = p
    for o in opts:
        p = idx.get(_key(o, extra))
        if not p:
            continue
        if kind in ("deposit", "saving"):
            p["options"].append({"term": int(num(o.get("save_trm")) or 0),
                                 "rateType": o.get("intr_rate_type_nm") or "",
                                 "rsrv": o.get("rsrv_type_nm") or "",
                                 "base": num(o.get("intr_rate")), "max": num(o.get("intr_rate2"))})
        elif kind in ("mortgage", "rent"):
            p["options"].append({"mrtg": o.get("mrtg_type_nm") or "",
                                 "rpay": o.get("rpay_type_nm") or "",
                                 "rateType": o.get("lend_rate_type_nm") or "",
                                 "min": num(o.get("lend_rate_min")), "max": num(o.get("lend_rate_max")),
                                 "avg": num(o.get("lend_rate_avg"))})
        else:
            g = {}
            for k in ("1", "4", "5", "6", "10", "11", "12", "13", "avg"):
                g[k] = num(o.get("crdt_grad_" + k))
            p["options"].append({"rateType": o.get("crdt_lend_rate_type_nm") or "", "grades": g})
    return [p for p in idx.values() if p["options"]]


# ---------------------------------------------------------------------------
# 이력(은행별 대표 금리) 계산
# ---------------------------------------------------------------------------
def bank_snapshot(products):
    """은행별 대표값: 예금/적금 12개월 최고우대금리, 대출 최저금리, 신용대출 평균금리"""
    snap = {}
    def put(kind, bank, v, better):
        if v is None:
            return
        d = snap.setdefault(kind, {})
        if bank not in d or better(v, d[bank]):
            d[bank] = v
    for kind in ("deposit", "saving"):
        for p in products.get(kind, []):
            for o in p["options"]:
                if o["term"] == 12:
                    put(kind, p["bank"], o["max"] or o["base"], lambda a, b: a > b)
    for kind in ("mortgage", "rent"):
        for p in products.get(kind, []):
            for o in p["options"]:
                put(kind, p["bank"], o["min"], lambda a, b: a < b)
    for p in products.get("credit", []):
        for o in p["options"]:
            if o["rateType"].startswith("대출금리"):
                put("credit", p["bank"], o["grades"].get("avg"), lambda a, b: a < b)
    return snap


def update_history(products, today_str):
    path = os.path.join(DATA, "history.json")
    hist = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
    snap = bank_snapshot(products)
    for kind, banks in snap.items():
        for bank, v in banks.items():
            series = hist.setdefault(kind, {}).setdefault(bank, [])
            series[:] = [x for x in series if x[0] != today_str]
            series.append([today_str, round(v, 3)])
            series.sort()
            del series[:-400]  # 최근 400회분만 보관
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False)
    return hist


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def write_output(payload):
    os.makedirs(DATA, exist_ok=True)
    js = "window.FIN_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    with open(os.path.join(DATA, "fin_data.js"), "w", encoding="utf-8") as f:
        f.write(js)
    log("저장 완료 -> data/fin_data.js (%.0f KB)" % (len(js.encode("utf-8")) / 1024))


def load_previous():
    path = os.path.join(DATA, "fin_data.js")
    if not os.path.exists(path):
        return {}
    try:
        txt = open(path, encoding="utf-8").read()
        return json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))
    except Exception:
        return {}


def run_real(check_only=False):
    cfg = load_config()
    if not cfg["ecos_key"] and not cfg["finlife_key"]:
        log("API 키가 없습니다. config.json에 ecos_key / finlife_key를 입력하거나 --demo로 실행하세요.")
        sys.exit(1)
    prev = load_previous()
    today_str = date.today().isoformat()
    payload = {"meta": {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "demo": False,
                        "errors": [], "sources": ["한국은행 ECOS Open API", "금융감독원 금융상품통합비교공시 API"]},
               "series": {}, "keystats": [], "products": {}, "history": {}}

    if cfg["ecos_key"]:
        for k, spec in ECOS_SERIES.items():
            try:
                s = fetch_ecos_series(cfg["ecos_key"], spec)
                payload["series"][k] = s
                last = s["points"][-1] if s["points"] else None
                log("ECOS  %-28s %4d건  최근 %s" % (spec[0], len(s["points"]), last))
            except Exception as e:
                payload["meta"]["errors"].append("ECOS %s: %s" % (spec[0], e))
                log("ECOS  %-28s 실패: %s" % (spec[0], e))
                if k in prev.get("series", {}):
                    payload["series"][k] = prev["series"][k]  # 이전 값 유지
        try:
            payload["keystats"] = fetch_ecos_keystats(cfg["ecos_key"])
            log("ECOS  100대 통계지표 %d건" % len(payload["keystats"]))
        except Exception as e:
            payload["meta"]["errors"].append("ECOS 100대지표: %s" % e)
            payload["keystats"] = prev.get("keystats", [])
    else:
        payload["meta"]["errors"].append("ECOS 키 없음 - 시장지표 생략")

    if cfg["finlife_key"]:
        for kind, api in FINLIFE_TYPES.items():
            try:
                b, o = fetch_finlife_raw(cfg["finlife_key"], api)
                payload["products"][kind] = normalize(kind, b, o)
                log("FINLIFE %-9s 상품 %3d개" % (kind, len(payload["products"][kind])))
            except Exception as e:
                payload["meta"]["errors"].append("FINLIFE %s: %s" % (kind, e))
                log("FINLIFE %-9s 실패: %s" % (kind, e))
                payload["products"][kind] = prev.get("products", {}).get(kind, [])
    else:
        payload["meta"]["errors"].append("FINLIFE 키 없음 - 상품 비교 생략")

    if check_only:
        log("점검 완료. 오류 %d건" % len(payload["meta"]["errors"]))
        for e in payload["meta"]["errors"]:
            log("  -", e)
        return

    os.makedirs(SNAP, exist_ok=True)
    if payload["products"]:
        with open(os.path.join(SNAP, today_str + ".json"), "w", encoding="utf-8") as f:
            json.dump(payload["products"], f, ensure_ascii=False)
        payload["history"] = update_history(payload["products"], today_str)
    write_output(payload)


# ---------------------------------------------------------------------------
# 데모(가상) 데이터 — 화면 확인용. 실제 수치가 아닙니다.
# ---------------------------------------------------------------------------
DEMO_BANKS = ["가람은행", "나래은행", "다온은행", "라온은행", "마루은행", "바다은행",
              "새솔은행", "아라은행", "자미은행", "차오름은행", "하늬은행", "온누리은행"]


def run_demo():
    rnd = random.Random(7)
    today = date.today()
    days = [today - timedelta(days=i) for i in range(1100, -1, -1)]
    days = [d for d in days if d.weekday() < 5]

    def walk(start, vol, drift=0.0, lo=None, hi=None):
        v, out = start, []
        for d in days:
            v += rnd.gauss(drift, vol)
            if lo is not None: v = max(lo, v)
            if hi is not None: v = min(hi, v)
            out.append([d.isoformat(), round(v, 3)])
        return out

    # 기준금리: 계단형 인하 경로
    steps = [(0, 3.50), (0.45, 3.25), (0.60, 3.00), (0.75, 2.75), (0.9, 2.50)]
    base = []
    for i, d in enumerate(days):
        r = [s[1] for s in steps if i / len(days) >= s[0]][-1]
        base.append([d.isoformat(), r])
    def follow(src, spread, vol):
        out, noise = [], 0
        for d, v in src:
            noise = noise * 0.97 + rnd.gauss(0, vol)
            out.append([d, round(v + spread + noise, 3)])
        return out
    series = {}
    def S(k, pts):
        spec = ECOS_SERIES[k]
        series[k] = {"name": spec[0], "group": spec[1], "unit": spec[2], "cycle": spec[4], "points": pts}
    S("base_rate", base)
    S("call", follow(base, -0.03, 0.01))
    S("cd91", follow(base, 0.12, 0.012))
    S("ktb3", follow(base, -0.15, 0.02))
    S("ktb10", follow(base, 0.10, 0.022))
    S("corp3", follow(base, 0.40, 0.02))
    S("usdkrw", walk(1300, 6, 0.08, 1180, 1520))
    S("jpykrw", walk(960, 5, -0.02, 820, 1050))
    S("eurkrw", walk(1420, 7, 0.06, 1300, 1650))
    S("kospi", walk(2500, 22, 0.6, 2000, 4200))
    S("kosdaq", walk(820, 9, 0.05, 600, 1100))
    months = []
    y, m = today.year, today.month
    for _ in range(132):
        months.append("%04d-%02d" % (y, m))
        m -= 1
        if m == 0: y, m = y - 1, 12
    months.reverse()
    cpi, v = [], 100.0
    for i, mm in enumerate(months):
        v *= 1 + (0.0025 if 60 < i < 90 else 0.0016) + rnd.gauss(0, 0.0012)
        cpi.append([mm, round(v, 2)])
    S("cpi", cpi)
    S("dep_rate", [[mm, round(2.2 + 1.3 * math.sin(i / 25) + rnd.gauss(0, .05), 2)] for i, mm in enumerate(months)])
    S("loan_rate", [[mm, round(3.9 + 1.4 * math.sin(i / 25) + rnd.gauss(0, .05), 2)] for i, mm in enumerate(months)])

    keystats = [{"cls": c, "name": n, "value": v, "unit": u, "cycle": "(가상)"} for c, n, v, u in [
        ("시장금리", "한국은행 기준금리", base[-1][1], "%"), ("시장금리", "국고채수익률(3년)", series["ktb3"]["points"][-1][1], "%"),
        ("환율", "원/달러 환율(종가)", series["usdkrw"]["points"][-1][1], "원"), ("주식", "KOSPI", series["kospi"]["points"][-1][1], "pt"),
        ("물가", "소비자물가지수", cpi[-1][1], "2020=100"), ("성장률", "경제성장률(실질, 계절조정 전기대비)", 0.6, "%"),
        ("고용", "실업률", 2.8, "%"), ("통화량", "M2(광의통화, 평잔)", 4180000.0, "십억원")]]

    joins = ["스마트폰", "인터넷,스마트폰", "영업점,인터넷,스마트폰", "영업점"]
    specials = ["급여이체 시 0.2%p, 카드 실적 30만원 이상 0.1%p", "첫 거래 고객 0.3%p",
                "마케팅 동의 0.1%p, 자동이체 0.2%p", "없음", "모바일 가입 0.15%p, 오픈뱅킹 등록 0.1%p"]
    products = {k: [] for k in FINLIFE_TYPES}
    for bi, bank in enumerate(DEMO_BANKS):
        lvl = rnd.uniform(-0.35, 0.35)
        for j in range(rnd.randint(1, 3)):
            opts = []
            for t in (1, 3, 6, 12, 24, 36):
                b = round(2.0 + lvl + 0.08 * math.log(t + 1) + rnd.uniform(-.1, .1), 2)
                opts.append({"term": t, "rateType": "단리", "rsrv": "", "base": b,
                             "max": round(b + rnd.choice([0, .2, .3, .5, .8]), 2)})
            products["deposit"].append({"bank": bank, "code": "D%02d%d" % (bi, j), "name": "%s %s정기예금" % (bank[:-2], ["e-", "더", "플러스"][j]),
                                        "joinWay": rnd.choice(joins), "month": today.strftime("%Y%m"), "special": rnd.choice(specials),
                                        "member": "실명의 개인", "maturity": "만기 후 1개월 이내 기본금리의 50%", "note": "가상 데이터", "limit": None, "deny": "1", "options": opts})
        for j in range(rnd.randint(1, 2)):
            opts = []
            for rs in ("정액적립식", "자유적립식"):
                for t in (6, 12, 24, 36):
                    b = round(2.4 + lvl + 0.1 * math.log(t) + rnd.uniform(-.15, .15), 2)
                    opts.append({"term": t, "rateType": rnd.choice(["단리", "복리"]), "rsrv": rs, "base": b,
                                 "max": round(b + rnd.choice([.3, .5, 1.0, 1.5, 2.5]), 2)})
            products["saving"].append({"bank": bank, "code": "S%02d%d" % (bi, j), "name": "%s %s적금" % (bank[:-2], ["희망", "챌린지"][j]),
                                       "joinWay": rnd.choice(joins), "month": today.strftime("%Y%m"), "special": rnd.choice(specials),
                                       "member": "만 19세 이상 개인", "maturity": "만기 후 기본금리의 30%", "note": "가상 데이터", "limit": rnd.choice([None, 500000, 1000000]), "deny": "1", "options": opts})
        for kind in ("mortgage", "rent"):
            opts = []
            mrtgs = ["아파트", "아파트외"] if kind == "mortgage" else [""]
            for mg in mrtgs:
                for rp in ("분할상환방식", "일시상환방식"):
                    for rt in ("고정금리", "변동금리"):
                        lo = round(3.4 + lvl + (0.2 if rt == "고정금리" else 0) + (0.1 if mg == "아파트외" else 0) + rnd.uniform(-.2, .2) - (0.3 if kind == "rent" else 0), 2)
                        hi = round(lo + rnd.uniform(1.0, 2.2), 2)
                        opts.append({"mrtg": mg, "rpay": rp, "rateType": rt, "min": lo, "max": hi, "avg": round(lo + (hi - lo) * .35, 2)})
            products[kind].append({"bank": bank, "code": kind[0].upper() + str(bi), "name": "%s %s" % (bank[:-2], "주택담보대출" if kind == "mortgage" else "전세자금대출"),
                                   "joinWay": rnd.choice(joins), "month": today.strftime("%Y%m"), "cost": "인지세 50% 고객 부담",
                                   "earlyFee": "3년 이내 상환 시 최대 1.2%", "delay": "약정금리+3%p", "limitTxt": "LTV 범위 내 최대 10억원", "options": opts})
        g = {}
        start = 4.3 + lvl
        for i, k in enumerate(("1", "4", "5", "6", "10", "11", "12", "13")):
            g[k] = round(start + i * rnd.uniform(.4, 1.1), 2)
        g["avg"] = round(start + 1.2, 2)
        products["credit"].append({"bank": bank, "code": "C" + str(bi), "name": "%s 직장인신용대출" % bank[:-2], "joinWay": rnd.choice(joins),
                                   "month": today.strftime("%Y%m"), "type": "일반신용대출", "cb": "KCB",
                                   "options": [{"rateType": "대출금리", "grades": g},
                                               {"rateType": "기준금리", "grades": {k: round(3.1 + rnd.uniform(-.05, .05), 2) for k in g}}]})

    # 이력: 지난 120일 동안 매일 수집했다고 가정
    hist = {}
    for kind in ("deposit", "saving", "mortgage", "rent", "credit"):
        final = bank_snapshot(products).get(kind, {})
        for bank, v in final.items():
            arr, x = [], v + rnd.uniform(.2, .5)
            for i in range(120, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                x += (v - x) * 0.04 + rnd.gauss(0, 0.01)
                if rnd.random() < .03: x += rnd.choice([-.1, .1])
                arr.append([d, round(v if i == 0 else x, 3)])
            hist.setdefault(kind, {})[bank] = arr
    payload = {"meta": {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "demo": True, "errors": [],
                        "sources": ["가상(데모) 데이터 — 실제 시장·은행 수치가 아닙니다"]},
               "series": series, "keystats": keystats, "products": products, "history": hist}
    write_output(payload)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        run_real(check_only="--check" in sys.argv)
