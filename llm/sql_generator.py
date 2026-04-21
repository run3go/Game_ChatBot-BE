import re
import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import SQLWithUIType, QuestionAnalysis
from llm.llm_monitor import log_llm_call, TokenCountCallback

class SQLGenerator:

    def __init__(self, llm):
        self.llm = llm
        self.model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    @staticmethod
    def _build_term_rules(abbr_hints: str) -> str:
        """abbr_hints의 A→B 매핑에서 SQL 값 치환 전용 지시 생성. src=dst 동어반복 제외."""
        import re as _re
        rules = []
        column_hints = []
        for h in abbr_hints.split(", "):
            tag_match = _re.search(r'\[([^\]]+)\]$', h)
            tag = tag_match.group(1) if tag_match else ""

            if "→" in h:
                src, dst_full = h.split("→", 1)
                src = src.strip()
                dst = _re.sub(r'\s*\[[^\]]+\]$', '', dst_full).strip()
                if src != dst:
                    rules.append(f"- 질문의 '{src}' → '{dst}' ({dst_full.strip()})")
                name = dst
            else:
                name = _re.sub(r'\s*\[[^\]]+\]$', '', h).strip()

            if tag == "아크패시브 클래스":
                column_hints.append(f"- '{name}'은 아크패시브 클래스명 → ark_passive_effects_tb.effect_name = '{name}' 으로 유저 필터링")
            elif tag == "직업":
                column_hints.append(f"- '{name}'은 직업명 → armory_profile_tb.character_class_name = '{name}' 으로 유저 필터링")

        all_rules = rules + column_hints
        if not all_rules:
            return ""
        return "[용어 치환 힌트 - 문맥에 맞게 참고]\n" + "\n".join(all_rules)

    def generate(self, question: str, analysis: QuestionAnalysis, schema, nicknames: list[str] | None = None, error: str | None = None, few_shots: str = "", abbr_hints: str = ""):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            [공통 SQL 규칙]
            - 반드시 [스키마]에 명시된 테이블만 사용해. 단, [유사 예시]에 등장하는 테이블은 예외적으로 사용 가능.
            - 테이블 접두사는 lostark.를 사용해.
            - 동적 테이블(collected_at 존재): 단일 캐릭터 조회 시 WITH step00 AS (SELECT MAX(collected_at) AS recent_collect_time FROM ... WHERE character_name = '닉네임') 패턴으로 최신 시점을 구해.
            - 동적 테이블에서 유저 필터링 시(전체 유저 포함): 반드시 character_name별 MAX(collected_at)로 최신 시점을 먼저 구한 뒤 조인해서 필터링. 예) ark_passive_effects_tb에서 특정 패시브 보유 유저 추출 시 latest_passives CTE 선행 필수.
            - 정적 테이블(collected_at 없음, 예: lostark_skill_tripod): WITH 절 없이 바로 조회해.
            - 동점자 포함 상위 N개: ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES.
            - 교집합 없는 데이터 추출: NOT EXISTS.
            - 동적 테이블 2개 조인: WITH 절에서 각 테이블의 최신 시점을 별도로 구한 뒤 메인 쿼리에서 조인해.
            - 여러 통계와 리스트를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리를 사용해.
            - 정규식에서 대괄호 내부 텍스트 추출 시 반드시 '\[(.*?)\]' 패턴을 사용할 것. '\[(.?)\]'처럼 *를 생략하면 값이 잘려 오류가 발생한다.
            - JOIN 시 컬럼은 반드시 테이블 alias를 붙여라
            - 한국어 서수 비교: '중 이하' → stagger IN ('없음', '하', '중'), '중 이상' → stagger IN ('중', '중상', '상', '최상'). '이하'는 해당 값 포함 그 아래, '이상'은 해당 값 포함 그 위. IN 절 반대 방향으로 쓰면 틀린 결과가 나오므로 주의.
            - 질문에서 명시한 스킬명·룬명·룬등급 조건은 CTE뿐 아니라 메인 쿼리에도 반드시 유지해. 예) 특정 스킬의 룬 통계를 묻는 경우 메인 SELECT에 WHERE skill_name = '...' AND rune_name = '...' AND rune_grade = '...' 조건이 모두 있어야 함.

            {error_feedback}

            [response_format별 SQL 규칙]
            - COUNT: COUNT(*) 단일 값만 반환. AS 별칭은 의미 있게 지정.
            - COUNT_LIST: GROUP BY + COUNT(*). 전체 유저 통계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인.
            - VALUE: SUM·AVG 등 단일 집계 수치 하나만 반환. 절대 행 전체를 반환하지 마.
            - TEXT / DISPLAY / LIST: 동적 테이블 조회 시 WITH step00 패턴으로 최신 시점을 구한 뒤 조건에 맞는 행을 반환. 정적 테이블(collected_at 없음, 예: lostark_skill_tripod)만 조회하는 경우 WITH 절 없이 바로 조회해.
              "가장 높은/낮은 ~가 뭐야?" 처럼 특정 대상(행)을 찾는 질문은 ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES로 행을 반환해. MAX() 단독으로 집계 수치만 반환하면 어떤 대상인지 알 수 없으므로 절대 금지.
            - COMPARE(캐릭터 간): 캐릭터별로 WITH latest_캐릭터명 AS (SELECT MAX(collected_at) AS recent_collect_time FROM ... WHERE character_name = '캐릭터명') CTE를 각각 구성. FROM 절 없이 캐릭터별 서브쿼리를 컬럼으로 분리하고 json_build_object로 캡슐화. AS "캐릭터명_data". to_jsonb(row) 및 to_jsonb(s.*) 사용 금지 — 반드시 명시적 컬럼으로 구성.
            - COMPARE(시점 비교): LAG 윈도우 함수로 이전 수집 시점의 값을 추출하고, 변경 여부(is_changed)와 변경 전/후 값을 함께 행 단위로 반환. 이전값은 prev_* 컬럼, 현재값은 current_* 컬럼으로 명명.
            - COMPARE(어제/이전 시점 비교 - "어제랑", "이전이랑", "달라진 점"): NOW() - INTERVAL 기준으로 자르면 결과가 없을 수 있음. 반드시 SELECT DISTINCT collected_at ORDER BY collected_at DESC LIMIT 2 로 최근 2개 스냅샷을 구한 뒤 그 두 시점 간 변경사항을 비교해.
            - COMPARE(강화 시점 탐지 - "재련 시점", "언제 강화", "몇 강 찍은 시점"): LAG(honing_level) OVER (PARTITION BY type ORDER BY collected_at)로 이전값과 비교해서 값이 바뀐 collected_at을 강화 시점으로 반환해. armory_equipment_tb 사용. ⚠️ 이 때 CTE에서 MAX(collected_at) 단일 시점을 쓰면 LAG 비교 대상이 없어 결과가 항상 비어버림. 반드시 기간 조건(collected_at >= NOW() - INTERVAL '...')으로 전체 이력을 가져온 뒤 LAG 적용할 것.

            [category별 SQL 규칙]
            ⚠️ GLOBAL_* 카테고리 공통: character_name 조건으로 특정 유저 지정 절대 금지.
            - GLOBAL_SKILL: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 armory_skills_tb 등 캐릭터 테이블 사용 가능. ⚠️ 특정 스킬/룬 통계 집계 시 GROUP BY 또는 집계 함수 전후로 skill_name·rune_name·rune_grade 필터 조건이 반드시 메인 쿼리에 있어야 함. 누락 시 전체 스킬/룬 데이터가 집계되는 오류 발생.
            - GLOBAL_ARK_PASSIVE: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 ark_passive_effects_tb 등 캐릭터 테이블 사용 가능.
            - GLOBAL_ARK_GRID: [스키마]에 있는 테이블 자유롭게 사용. 전체 유저 집계 시 캐릭터 테이블 사용 가능.
            - GLOBAL_ENGRAVING: 각인 효과 설명·레벨별 차이 질문은 반드시 lostark.engrave 테이블에서 search_name LIKE '%각인명%' 조건으로 조회해. armory_engravings_tb는 유저 장착 통계/비율을 묻는 경우에만 사용. ⚠️ character_name = '닉네임' 같은 더미 플레이스홀더 절대 금지.
            - GLOBAL_PROFILE: 전체 유저 집계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인.
            - SKILL + COMPARE: 반드시 armory_skills_tb와 armory_gem_tb를 함께 사용해. 스킬 정보에 해당 스킬의 보석 이름 목록(gems)을 jsonb_agg(g.name)으로 포함시켜.
            - PROFILE(단순 레벨 조회 시) : character_level과 item_avg_level을 반드시 함께 SELECT.
            - PROFILE(강화 수치 / 장비 강화 조회 시): 반드시 armory_equipment_tb를 사용해. armory_profile_tb에는 honing_level 컬럼이 없으므로 절대 사용 금지. SELECT 절에 반드시 type, name, honing_level, advanced_honing_level 4개 컬럼을 모두 포함해. ⚠️ type과 name을 생략하면 어느 부위 장비인지 절대 알 수 없으므로 honing_level만 단독으로 SELECT하는 것은 금지. 질문에 특정 장비명(무기, 투구 등)이 없으면 반드시 type IN ('무기', '투구', '상의', '하의', '장갑', '어깨') 조건으로 전 부위를 조회. 질문에 특정 장비 부위가 있어도 반드시 WHERE type = '...' 조건을 명시해.
            - PROFILE(어빌리티 스톤 조회 - "돌", "스톤"): armory_equipment_tb에서 WHERE type = '어빌리티 스톤' 조건으로 name, additional_effect를 조회해. "97돌", "3/4돌" 같은 표현은 스톤 이름이 아니므로 name 조건으로 쓰지 말고 additional_effect를 반환해서 LLM이 판단하게 해.
            - PROFILE(낙원력 조회): armory_equipment_tb에서 WHERE type = '보주' 조건으로 additional_effect를 조회해. armory_profile_tb의 item_avg_level은 낙원력이 아님.
            - PROFILE(팔찌 조회): armory_equipment_tb에서 WHERE type = '팔찌' 조건으로 조회해. armory_profile_tb 절대 사용 금지.
            - PROFILE(기간별 성장 추이 - "성장", "한 달", "변화"): armory_profile_tb에서 해당 기간의 모든 스냅샷을 collected_at 순으로 조회하고 반드시 collected_at, item_avg_level, combat_power를 함께 반환해. COUNT(*) 단일값 반환 금지.

            {few_shots}

            [용어 힌트 - 질문 속 표현과 DB 정식 명칭 매핑]
            {abbr_hints}

            {term_rules}

            [질문]
            {question}

            [분석]
            {analysis}
            ※ response_format이 [유사 예시]의 분석 유형과 일치하는 예시를 우선 참고해.

            [대상 닉네임]
            {nicknames}
            - 닉네임이 있으면: 반드시 WHERE character_name = '...' 조건으로 사용하고 절대 생략하지 마.
            - 닉네임이 없으면(없음): WHERE character_name 조건을 절대 추가하지 마. '닉네임' 같은 임의 플레이스홀더도 절대 사용 금지.

            [스키마]
            {schema}

        """)

        structured_llm = self.llm.with_structured_output(SQLWithUIType)
        chain = (prompt | structured_llm).with_retry(stop_after_attempt=2)

        # 스키마 요약 (로깅용 - 테이블명만)
        schema_tables = list(schema.keys()) if isinstance(schema, dict) else str(schema)[:200]

        start_time = time.time()
        cb = TokenCountCallback()
        detail = {
            "input": {
                "abbr_hints": abbr_hints or "없음",
                "schema_tables": schema_tables,
                "few_shots": few_shots if few_shots else "없음",
                "error_feedback": error or "없음",
            },
            "output": {},
        }

        try:
            result = chain.invoke({
                    "question": question,
                    "analysis": analysis,
                    "nicknames": ", ".join(nicknames) if nicknames else "없음",
                    "schema": schema,
                    "error_feedback": f"[이전 시도 오류 - 반드시 수정]\n{error}\n위 오류를 반드시 수정해서 다시 생성해." if error else "",
                    "few_shots": few_shots,
                    "abbr_hints": abbr_hints or "없음",
                    "term_rules": self._build_term_rules(abbr_hints) if abbr_hints else "",
            }, config={"callbacks": [cb]})

            if result is None:
                raise ValueError("SQL 생성 결과가 없습니다.")

            cleaned_sql = self._clean_sql(result.sql)

            detail["output"] = {
                "sql": cleaned_sql,
                "ui_type": result.ui_type,
            }

            log_llm_call(
                generator_type="sql",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                detail=detail,
            )

            return cleaned_sql, result.ui_type

        except Exception as e:
            log_llm_call(
                generator_type="sql",
                model_name=self.model_name,
                start_time=start_time,
                callback=cb,
                success=False,
                error_message=str(e),
                detail=detail,
            )
            raise

    def generate_validated(self, question: str, analysis: QuestionAnalysis, schema: dict, nicknames: list[str] | None = None, few_shots: str = "", all_tables: set | None = None, abbr_hints: str = "") -> str:
        allowed = all_tables if all_tables is not None else set(schema.keys())

        def _check_invalid(sql: str) -> set:
            return {re.sub(r'\W', '', w.split(".")[-1]) for w in sql.split() if "lostark." in w} - allowed

        sql, _ = self.generate(question, analysis, schema, nicknames, few_shots=few_shots, abbr_hints=abbr_hints)
        invalid = _check_invalid(sql)
        if not invalid:
            return sql

        sql, _ = self.generate(question, analysis, schema, nicknames, few_shots=few_shots, abbr_hints=abbr_hints,
                               error=f"허용되지 않은 테이블 사용: {invalid}. 반드시 [스키마]에 있는 테이블만 사용해.")
        invalid = _check_invalid(sql)
        if invalid:
            raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {invalid}")
        return sql

    def _clean_sql(self, sql: str):
        sql = (
            sql
            .replace("```sql", "")
            .replace("```", "")
            .strip()
        )
        sql_upper = sql.upper()
        if "LIMIT" not in sql_upper and "FETCH FIRST" not in sql_upper:
            sql = sql.rstrip(";") + "\nLIMIT 200"
        return sql
