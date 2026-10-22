# 금융 공공데이터 모니터 (호박공장메이커스페이스용)

공공 API에서 매일 데이터를 받아 두 개의 HTML 화면으로 보여 줍니다.

| 파일 | 역할 |
|---|---|
| `fin_update.py` | 데이터 수집 프로그램 (Python 표준 라이브러리만 사용) |
| `dashboard.html` | 금리·환율·주가·물가·예대금리 그래프, 금리 전달 다이어그램, 변화표·상관표, 자동 동향 요약, 100대 통계지표 |
| `bank_compare.html` | 은행권 정기예금·적금·주담대·전세대출·신용대출 비교, 만기 수령액·월 상환액 계산기, 은행별 금리 추이, 최대 4개 상품 나란히 비교 |
| `config.json` | API 인증키 입력 |
| `run_update.bat` / `install_daily_task.bat` | Windows 매일 자동 실행 |

## 1. API 키 발급 (무료)
1. **한국은행 ECOS**: https://ecos.bok.or.kr/api → 회원가입 → 인증키 신청 (즉시 발급)
2. **금융감독원 금융상품통합비교공시**: https://finlife.fss.or.kr → 오픈 API → 인증키 신청

두 키를 `config.json`에 넣습니다. (환경변수 `ECOS_API_KEY`, `FINLIFE_API_KEY`도 가능)

## 2. 실행
```
python fin_update.py --check   # 키와 통계코드 연결 점검
python fin_update.py           # 수집 → data/fin_data.js 생성
```
그다음 두 HTML 파일을 더블클릭해 브라우저로 엽니다. (차트 라이브러리를 CDN에서 불러오므로 인터넷 연결 필요)

키 없이 화면만 먼저 보려면 `python fin_update.py --demo` — **가상 데이터**이며 화면 상단에 경고가 표시됩니다.

## 3. 매일 자동 업데이트
- **Windows**: `install_daily_task.bat`을 더블클릭 → 매일 09:10 실행 등록. 로그는 `data/update_log.txt`.
- **macOS/Linux**: `crontab -e` 에 추가
  `10 9 * * * cd /경로/finance_monitor && /usr/bin/python3 fin_update.py >> data/update_log.txt 2>&1`

매일 실행할수록 `data/history.json`에 은행별 대표 금리가 쌓여, 비교 화면의 "금리 추이" 그래프가 길어집니다.
(`data/snapshots/날짜.json`에는 그날의 전체 상품 원본이 저장됩니다.)

## 4. 지표 추가·수정
`fin_update.py` 상단 `ECOS_SERIES`에 한 줄을 추가하면 됩니다.
통계표 코드·항목 코드는 ECOS 개발명세서 → 통계코드검색에서 확인하세요.
특정 지표가 실패해도 나머지는 계속 수집되고, 실패 항목은 이전 값이 유지되며 화면에 표시됩니다.

## 참고
- 예적금 금리는 공시 기준(세전)이며 우대금리는 조건 충족 시에만 적용됩니다.
- 대출 금리는 공시 범위와 전월 평균이며 실제 금리는 신용도·담보에 따라 다릅니다.
- 화면의 요약·상관분석은 통계적 참고 자료이며 투자 권유가 아닙니다.
