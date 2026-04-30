COMMON_RULES = """[공통 SQL 규칙]
- 반드시 [스키마]에 명시된 테이블만 사용해. 단, [유사 예시]에 등장하는 테이블은 예외적으로 사용 가능.
- 테이블 접두사는 lostark.를 사용해.
- 동적 테이블(collected_at 존재): 단일 캐릭터 조회 시 WITH step00 AS (SELECT MAX(collected_at) AS recent_collect_time FROM ... WHERE character_name = '닉네임') 패턴으로 최신 시점을 구해.
- 동적 테이블에서 유저 필터링 시(전체 유저 포함): 반드시 character_name별 MAX(collected_at)로 최신 시점을 먼저 구한 뒤 조인해서 필터링. 예) ark_passive_effects_tb에서 특정 패시브 보유 유저 추출 시 latest_passives CTE 선행 필수.
- ⚠️ 전체 유저 집계 시 여러 동적 테이블을 조인하는 경우: 필터용 테이블뿐 아니라 집계 대상 테이블에도 반드시 character_name별 MAX(collected_at) CTE를 적용해.
- 정적 테이블(collected_at 없음, 예: lostark_skill_tripod): WITH 절 없이 바로 조회해.
- 동점자 포함 상위 N개: ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES.
- 교집합 없는 데이터 추출: NOT EXISTS.
- 동적 테이블 2개 조인: WITH 절에서 각 테이블의 최신 시점을 별도로 구한 뒤 메인 쿼리에서 조인해.
- 여러 통계와 리스트를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리를 사용해.
- 정규식에서 대괄호 내부 텍스트 추출 시 반드시 '\\[(.*?)\\]' 패턴을 사용할 것. '\\[(.?)\\]'처럼 *를 생략하면 값이 잘려 오류가 발생한다.
- JOIN 시 컬럼은 반드시 테이블 alias를 붙여라.
- 한국어 서수 비교: '중 이하' → stagger IN ('없음', '하', '중'), '중 이상' → stagger IN ('중', '중상', '상', '최상'). '이하'는 해당 값 포함 그 아래, '이상'은 해당 값 포함 그 위. IN 절 반대 방향으로 쓰면 틀린 결과가 나오므로 주의.
- 질문에서 명시한 스킬명·룬명·룬등급 조건은 CTE뿐 아니라 메인 쿼리에도 반드시 유지해."""

RESPONSE_FORMAT_RULES = """[response_format별 SQL 규칙]
- COUNT: 동적 테이블 조회 시 WITH step00 패턴으로 최신 시점을 구한 뒤 COUNT(*) 단일 값만 반환. AS 별칭은 의미 있게 지정.
- COUNT_LIST: GROUP BY + COUNT(*). 전체 유저 통계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인.
- VALUE: 동적 테이블 조회 시 WITH step00 패턴으로 최신 시점을 구한 뒤 SUM·AVG 등 단일 집계 수치 하나만 반환. 절대 행 전체를 반환하지 마.
- TEXT / DISPLAY / LIST: 동적 테이블 조회 시 WITH step00 패턴으로 최신 시점을 구한 뒤 조건에 맞는 행을 반환. 정적 테이블(collected_at 없음, 예: lostark_skill_tripod)만 조회하는 경우 WITH 절 없이 바로 조회해.
  "가장 높은/낮은 ~가 뭐야?" 처럼 특정 대상(행)을 찾는 질문은 ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES로 행을 반환해. MAX() 단독으로 집계 수치만 반환하면 어떤 대상인지 알 수 없으므로 절대 금지.
- COMPARE(캐릭터 간): 캐릭터별로 WITH latest_캐릭터명 AS (SELECT MAX(collected_at) AS recent_collect_time FROM ... WHERE character_name = '캐릭터명') CTE를 각각 구성. FROM 절 없이 캐릭터별 서브쿼리를 컬럼으로 분리하고 json_build_object로 캡슐화. AS "캐릭터명_data". to_jsonb(row) 및 to_jsonb(s.*) 사용 금지 — 반드시 명시적 컬럼으로 구성.
- COMPARE(시점 비교): LAG 윈도우 함수로 이전 수집 시점의 값을 추출하고, 변경 여부(is_changed)와 변경 전/후 값을 함께 행 단위로 반환. 이전값은 prev_* 컬럼, 현재값은 current_* 컬럼으로 명명.
- COMPARE(어제/이전 시점 비교 - "어제랑", "이전이랑", "달라진 점"): NOW() - INTERVAL 기준으로 자르면 결과가 없을 수 있음. 반드시 SELECT DISTINCT collected_at ORDER BY collected_at DESC LIMIT 2 로 최근 2개 스냅샷을 구한 뒤 그 두 시점 간 변경사항을 비교해.
- COMPARE(강화 시점 탐지 - "재련 시점", "언제 강화", "몇 강 찍은 시점"): LAG(honing_level) OVER (PARTITION BY type ORDER BY collected_at)로 이전값과 비교해서 값이 바뀐 collected_at을 강화 시점으로 반환해. armory_equipment_tb 사용. ⚠️ 이 때 CTE에서 MAX(collected_at) 단일 시점을 쓰면 LAG 비교 대상이 없어 결과가 항상 비어버림. 반드시 기간 조건(collected_at >= NOW() - INTERVAL '...')으로 전체 이력을 가져온 뒤 LAG 적용할 것."""


_GLOBAL_COMMON = """⚠️ GLOBAL_* 카테고리 공통: character_name 조건으로 특정 유저 지정 절대 금지.
⚠️ GLOBAL_* + 동적 테이블(collected_at 존재) 조회 시: 반드시 직업명·아크패시브 클래스 등 의미 있는 WHERE 필터 또는 GROUP BY 집계를 포함해야 함. 필터·집계 없이 캐릭터 테이블 전체를 SELECT하거나 개별 캐릭터 행을 raw로 반환하는 쿼리는 절대 생성 금지.
  정적 테이블(collected_at 없음, 예: lostark_skill_tripod, engrave)은 이 제한 없이 자유롭게 조회 가능."""

_CATEGORY_RULES: dict[str, str] = {
    "MARKET": """- MARKET: market_items_tb만 사용. character_name 조건 절대 금지. 1개당 단가 계산 시 current_min_price / bundle_count 사용.
  최신 시점 조회 시 WHERE 아이템 조건과 함께 MAX(collected_at)를 사용하는 WITH latest_market CTE 패턴 사용.
  ⚠️ 시세 추이(기간 조회) 시 [유사 예시] 패턴과 무관하게 반드시 아래 CTE 구조 사용.
    bundle_count·yday_avg_price 사용 금지. GROUP BY DATE(collected_at) 반드시 포함:
    WITH daily_latest AS (
        SELECT MAX(collected_at) AS max_at
        FROM lostark.market_items_tb
        WHERE {아이템 조건} AND collected_at >= NOW() - INTERVAL '{N} days'
        GROUP BY DATE(collected_at)
    )
    SELECT collected_at, current_min_price,
        current_min_price - LAG(current_min_price) OVER (ORDER BY collected_at) AS price_diff
    FROM lostark.market_items_tb
    WHERE {아이템 조건} AND collected_at IN (SELECT max_at FROM daily_latest)
    ORDER BY collected_at ASC
  ⚠️ 각인서 등급 약어 해석 — 질문에 아래 표현이 있으면 반드시 grade로 변환:
    유각·유물각 → grade='유물', 전각·전설각 → grade='전설',
    영각·영웅각 → grade='영웅', 희각·희귀각 → grade='희귀', 고각·고급각 → grade='고급'
  ⚠️ 각인서 검색 시 [유사 예시] 패턴과 무관하게 반드시 아래 패턴 사용. name 정확 매칭 금지:
    WHERE item_type = '각인서' AND grade = '{등급}' AND name ILIKE '%{각인명}%'
    - 등급: 위 약어 변환표 또는 질문·abbr_hints에서 추출. 미지정 시 grade 조건 생략.
    - 각인명: abbr_hints 매핑 적용 후 '각인서'·등급·약어(유각 등) 단어를 모두 제거한 핵심어.
    - 예) '예둔 유각', '아드 유각'
          → item_type='각인서' AND grade='유물' AND name ILIKE '%예리한 둔기%'
          → item_type='각인서' AND grade='유물' AND name ILIKE '%아드레날린%'""",

    "AUCTION": """- AUCTION: 기본적으로 auction_items_tb만 사용. character_name 조건 절대 금지. 즉시구매가 조회 시 buy_price > 0 조건 포함. options JSONB 필터링 시 (options->>'옵션명')::numeric 캐스팅 사용.
  반드시 collected_at = (SELECT MAX(collected_at) FROM lostark.auction_items_tb) 조건으로 최신 스냅샷만 조회해. end_date > CURRENT_TIMESTAMP 조건은 추가하지 마.
  ⚠️ 장신구(반지·귀걸이·목걸이·팔찌) 조회 시 "3티어" 언급이 따로 없으면 반드시 tier = 4 조건을 포함해. tier = 3 사용 절대 금지.
  ⚠️ 닉네임이 있고 "장착한 아이템의 시세"를 묻는 경우: armory_equipment_tb를 CTE로 먼저 사용해 해당 캐릭터의 장착 아이템 옵션·품질을 추출한 뒤, 그 값 기준으로 auction_items_tb에서 유사 매물을 검색해. 이때만 armory_equipment_tb 사용이 허용되며, [유사 예시] 패턴을 반드시 참고해.
  ⚠️ 닉네임이 있고 "장착한 보석의 시세/가격/비용"을 묻는 경우: armory_gem_tb.name에는 '광휘' 접두사가 붙지만(예: '광휘 작열') auction_items_tb.name에는 '광휘'가 없음(예: '작열'). 반드시 armory_gem_tb CTE에서 REPLACE(name, '광휘', '작열') AS mapped_name으로 변환한 뒤 auction_items_tb와 조인해.
  ⚠️ 보석(item_type = '보석') 조회 시:
  - 보석 레벨(예: 8레벨, 10레벨)은 name 컬럼에 포함됨 → 반드시 name LIKE '%8레벨%' 형태로 사용. grade·level 등 다른 컬럼에 레벨 값을 넣는 것은 절대 금지.
  - grade 컬럼은 아이템 희귀도(고대·유물·전설 등)를 나타냄. 질문에 grade/등급을 명시하지 않으면 grade 조건을 절대 추가하지 마.
  - 특정 보석 종류(작열, 홍염 등)를 명시하지 않고 레벨·티어만 묻는 경우: 반드시 GROUP BY A.name으로 보석 종류별 결과를 반환하고 A.name, MIN(A.buy_price) AS min_price, ROUND(AVG(A.buy_price)) AS avg_price, COUNT(A.id) AS item_count를 함께 SELECT해.""",

    "SKILL": """- SKILL + COMPARE: 반드시 armory_skills_tb와 armory_gem_tb를 함께 사용해. 스킬 정보에 해당 스킬의 보석 이름 목록(gems)을 jsonb_agg(g.name)으로 포함시켜.""",

    "GLOBAL_SKILL": f"""{_GLOBAL_COMMON}
- GLOBAL_SKILL: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 armory_skills_tb 등 캐릭터 테이블 사용 가능. ⚠️ 특정 스킬/룬 통계 집계 시 GROUP BY 또는 집계 함수 전후로 skill_name·rune_name·rune_grade 필터 조건이 반드시 메인 쿼리에 있어야 함. 누락 시 전체 스킬/룬 데이터가 집계되는 오류 발생.""",

    "ENGRAVING": "",

    "GLOBAL_ENGRAVING": f"""{_GLOBAL_COMMON}
- GLOBAL_ENGRAVING: 각인 효과 설명·레벨별 차이 질문은 반드시 lostark.engrave 테이블에서 search_name LIKE '%각인명%' 조건으로 조회해. armory_engravings_tb는 유저 장착 통계/비율을 묻는 경우에만 사용. ⚠️ character_name = '닉네임' 같은 더미 플레이스홀더 절대 금지.""",

    "ARK_PASSIVE": "",

    "GLOBAL_ARK_PASSIVE": f"""{_GLOBAL_COMMON}
- GLOBAL_ARK_PASSIVE: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 ark_passive_effects_tb 등 캐릭터 테이블 사용 가능.""",

    "ARK_GRID": "",

    "GLOBAL_ARK_GRID": f"""{_GLOBAL_COMMON}
- GLOBAL_ARK_GRID: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 캐릭터 테이블 사용 가능.""",

    "PROFILE": """- PROFILE(단순 레벨 조회 시): character_level과 item_avg_level을 반드시 함께 SELECT.
- PROFILE(강화 수치 / 장비 강화 조회 시): 반드시 armory_equipment_tb를 사용해. armory_profile_tb에는 honing_level 컬럼이 없으므로 절대 사용 금지. SELECT 절에 반드시 type, name, honing_level, advanced_honing_level 4개 컬럼을 모두 포함해. ⚠️ type과 name을 생략하면 어느 부위 장비인지 절대 알 수 없으므로 honing_level만 단독으로 SELECT하는 것은 금지. 질문에 특정 장비명(무기, 투구 등)이 없으면 반드시 type IN ('무기', '투구', '상의', '하의', '장갑', '어깨') 조건으로 전 부위를 조회. 질문에 특정 장비 부위가 있어도 반드시 WHERE type = '...' 조건을 명시해.
- PROFILE(어빌리티 스톤 조회 - "돌", "스톤"): armory_equipment_tb에서 WHERE type = '어빌리티 스톤' 조건으로 name, additional_effect를 조회해. "97돌", "3/4돌" 같은 표현은 스톤 이름이 아니므로 name 조건으로 쓰지 말고 additional_effect를 반환해서 LLM이 판단하게 해.
- PROFILE(낙원력 조회): armory_equipment_tb에서 WHERE type = '보주' 조건으로 additional_effect를 조회해. armory_profile_tb의 item_avg_level은 낙원력이 아님.
- PROFILE(팔찌 조회): armory_equipment_tb에서 WHERE type = '팔찌' 조건으로 조회해. armory_profile_tb 절대 사용 금지.
- PROFILE(기간별 성장 추이 - "성장", "한 달", "변화"): armory_profile_tb에서 해당 기간의 모든 스냅샷을 collected_at 순으로 조회하고 반드시 collected_at, item_avg_level, combat_power를 함께 반환해. COUNT(*) 단일값 반환 금지.""",

    "GLOBAL_PROFILE": f"""{_GLOBAL_COMMON}
- GLOBAL_PROFILE: 전체 유저 집계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인.""",

    "COLLECTIBLE": "",
}


def get_category_rules(category: str) -> str:
    rules = _CATEGORY_RULES.get(category, "")
    if not rules:
        return ""
    return f"[category별 SQL 규칙]\n{rules}"
