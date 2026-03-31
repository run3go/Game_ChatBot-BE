from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from output_types import SQLWithUIType, QuestionAnalysis

class SQLGenerator:

    def __init__(self, llm):
        self.llm = llm

    def generate(self, question: str, analysis : QuestionAnalysis, schema, nicknames: list[str] | None = None, error: str | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            [SQL 출력 규칙]
            - 반드시 [스키마]에 명시된 테이블만 사용해. 그 외 테이블(예: characters, users, skills 등)은 절대 사용 금지.
            - 테이블에 접근할 때는 접두사로 lostark.를 사용해.
            - 동일 character_name에 대해 여러 시점의 데이터가 있을 경우, collected_at이 MAX인 행만 사용해.

            {error_feedback}
                                                  
            [response_format별 SQL 규칙]
            - COUNT: COUNT(*) 단일 값만 반환. json_agg 사용 금지. AS 별칭은 의미 있게 지정. (예: 황로드유_겁화_count)
            - COUNT_LIST: GROUP BY + COUNT(*) 로 항목별 개수 목록 반환. json_agg 사용 금지.
            - VALUE: 단일 수치 컬럼 하나만 반환.
            - COMPARE: 메인 쿼리에 FROM 절 없이, 캐릭터별 서브쿼리를 개별 컬럼(AS 캐릭터명_data)으로 분리하고 json_build_object로 캡슐화해.
            - DISPLAY: 반드시 아래 구조를 따라야 해. 최상위 SELECT에 FROM 절 없이, 테이블마다 서브쿼리 컬럼으로 구성해.
              AS 별칭은 테이블 원본 이름을 그대로 사용해. (예: AS armory_skills_tb)
              ※ 주의: AS 별칭은 반드시 가장 바깥쪽 서브쿼리 닫는 괄호 ) 뒤에 위치해야 해.
              SELECT
                (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{{테이블A}} t
                 WHERE t.character_name = '닉네임' AND t.collected_at = (SELECT MAX(t2.collected_at) FROM lostark.{{테이블A}} t2 WHERE t2.character_name = '닉네임')
                ) AS {{테이블A}},
                (SELECT COALESCE(json_agg(t.*), '[]'::json) FROM lostark.{{테이블B}} t
                 WHERE t.character_name = '닉네임' AND t.collected_at = (SELECT MAX(t2.collected_at) FROM lostark.{{테이블B}} t2 WHERE t2.character_name = '닉네임')
                ) AS {{테이블B}}

            [분석 규칙]
            - 여러 테이블의 통계(Count, Sum)와 리스트를 한 번에 가져올 때는 JOIN 대신 상호관련 서브쿼리를 사용해.

            [ui_type 결정 규칙]
            - SQL이 캐릭터 테이블 전체 컬럼(t.* 또는 *)을 반환하면 → [분석]의 category 그대로 반환 (SKILL, ENGRAVING, ARK_GRID 등)
            - SQL이 특정 컬럼만 반환하거나 COUNT·SUM 등 집계값이면 → TEXT

            [질문]
            {question}

            [분석]
            {analysis}

            [대상 닉네임]
            {nicknames}
            - 반드시 위 닉네임을 WHERE character_name = '...' 조건으로 사용해.
            - 닉네임이 있으면 절대 생략하지 마.

            [스키마]
            {schema}

        """)

        structured_llm = self.llm.with_structured_output(SQLWithUIType)
        chain = (prompt | structured_llm).with_retry(stop_after_attempt=2)


        result = chain.invoke({
                "question": question,
                "analysis": analysis,
                "nicknames": nicknames if nicknames else "",
                "schema": schema,
                "error_feedback": f"[이전 시도 오류 - 반드시 수정]\n{error}\n위 오류를 반드시 수정해서 다시 생성해." if error else "",
        })

        if result is None:
            raise ValueError("SQL 생성 결과가 없습니다.")
        return self._clean_sql(result.sql), result.ui_type

    def generate_validated(self, question: str, analysis: QuestionAnalysis, schema: dict, nicknames: list[str] | None = None) -> tuple[str, str, set]:
        sql, ui_type = self.generate(question, analysis, schema, nicknames)
        for attempt in range(2):
            used = {w.split(".")[-1] for w in sql.split() if "lostark." in w}
            invalid = used - set(schema.keys())
            if not invalid:
                return sql, ui_type, used
            if attempt == 1:
                raise ValueError(f"LLM이 허용되지 않은 테이블을 사용했습니다: {invalid}")
            sql, ui_type = self.generate(question, analysis, schema, nicknames, error=f"허용되지 않은 테이블 사용: {invalid}. 반드시 [스키마]에 있는 테이블만 사용해.")
        return sql, ui_type, used

    def _clean_sql(self, sql: str):
        return (
            sql
            .replace("```sql", "")
            .replace("```", "")
            .strip()
        )