import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import SQLWithUIType, QuestionAnalysis
from llm.llm_monitor import log_llm_call, TokenCountCallback

class SQLGenerator:

    def __init__(self, llm):
        self.llm = llm
        self.model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))

    def generate(self, question: str, analysis: QuestionAnalysis, schema, nicknames: list[str] | None = None, error: str | None = None, few_shots: str = "", abbr_hints: str = ""):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            [공통 SQL 규칙]
            - 반드시 [스키마]에 명시된 테이블만 사용해. 그 외 테이블은 절대 사용 금지.
            - 테이블 접두사는 lostark.를 사용해.
            - 동적 테이블(collected_at 존재): 단일 캐릭터 조회 시 WITH step00 AS (SELECT MAX(collected_at) AS recent_collect_time FROM ... WHERE character_name = '닉네임') 패턴으로 최신 시점을 구해.
            - 정적 테이블(collected_at 없음, 예: lostark_skill_tripod): WITH 절 없이 바로 조회해.
            - 동점자 포함 상위 N개: ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES.
            - 교집합 없는 데이터 추출: NOT EXISTS.
            - 동적 테이블 2개 조인: WITH 절에서 각 테이블의 최신 시점을 별도로 구한 뒤 메인 쿼리에서 조인해.
            - 여러 통계와 리스트를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리를 사용해.
            - 정규식에서 대괄호 내부 텍스트 추출 시 반드시 '\[(.*?)\]' 패턴을 사용할 것. '\[(.?)\]'처럼 *를 생략하면 값이 잘려 오류가 발생한다.

            {error_feedback}

            [response_format별 SQL 규칙]
            - COUNT: COUNT(*) 단일 값만 반환. AS 별칭은 의미 있게 지정.
            - COUNT_LIST: GROUP BY + COUNT(*). 전체 유저 통계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인.
            - VALUE: SUM·AVG 등 단일 집계 수치 하나만 반환. 절대 행 전체를 반환하지 마.
            - TEXT / DISPLAY / LIST: WITH step00 패턴으로 최신 시점을 구한 뒤 조건에 맞는 행을 반환.
              "가장 높은/낮은 ~가 뭐야?" 처럼 특정 대상(행)을 찾는 질문은 ORDER BY ... DESC FETCH FIRST 1 ROWS WITH TIES로 행을 반환해.
            - COMPARE(캐릭터 간): FROM 절 없이 캐릭터별 서브쿼리를 컬럼으로 분리하고 json_build_object로 캡슐화. AS "캐릭터명_data".
            - COMPARE(시점 비교): LAG 윈도우 함수로 이전 수집 시점의 값을 추출하고, 변경 여부(is_changed)와 변경 전/후 값을 함께 행 단위로 반환. 이전값은 prev_* 컬럼, 현재값은 current_* 컬럼으로 명명.

            [category별 SQL 규칙]
            - GLOBAL_SKILL: lostark.lostark_skill_tripod, lostark.lostark_skill_level 테이블만 사용. character_name 조건 및 armory_skills_tb 조인 절대 금지.
            - GLOBAL_ARK_PASSIVE: lostark.lostark_ark_passive_effects 계열 테이블만 사용. character_name 조건 및 캐릭터 테이블 조인 절대 금지.
            - GLOBAL_ARK_GRID: lostark.lostark_ark_grid_cores 계열 테이블만 사용. character_name 조건 및 캐릭터 테이블 조인 절대 금지.
            - GLOBAL_ENGRAVING: lostark.lostark_engravings 계열 테이블만 사용. character_name 조건 및 캐릭터 테이블 조인 절대 금지.
            - GLOBAL_PROFILE: 전체 유저 집계 시 character_name별 MAX(collected_at)로 최신 시점을 구한 뒤 조인. character_name 조건 없이 집계.
            - SKILL + COMPARE: 반드시 armory_skills_tb와 armory_gem_tb를 함께 사용해. 스킬 정보에 해당 스킬의 보석 이름 목록(gems)을 jsonb_agg(g.name)으로 포함시켜.
            - PROFILE(단순 레벨 조회 시) : character_level과 item_avg_level을 반드시 함께 SELECT.

            {few_shots}

            [약어 힌트 - 질문 속 약어와 정식 명칭 매핑]
            {abbr_hints}
            ※ 약어 힌트는 참고용임. 문맥상 약어가 아닌 일반 단어로 쓰인 경우 무시할 것.

            [질문]
            {question}

            [분석]
            {analysis}
            ※ response_format이 [유사 예시]의 분석 유형과 일치하는 예시를 우선 참고해.

            [대상 닉네임]
            {nicknames}
            - 반드시 위 닉네임을 WHERE character_name = '...' 조건으로 사용해.
            - 닉네임이 있으면 절대 생략하지 마.

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
                "few_shots": few_shots[:300] if few_shots else "없음",
                "error_feedback": error or "없음",
            },
            "output": {},
        }

        try:
            result = chain.invoke({
                    "question": question,
                    "analysis": analysis,
                    "nicknames": nicknames if nicknames else "",
                    "schema": schema,
                    "error_feedback": f"[이전 시도 오류 - 반드시 수정]\n{error}\n위 오류를 반드시 수정해서 다시 생성해." if error else "",
                    "few_shots": few_shots,
                    "abbr_hints": abbr_hints or "없음",
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
            return {w.split(".")[-1] for w in sql.split() if "lostark." in w} - allowed

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
