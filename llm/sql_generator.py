import re
import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import SQLWithUIType, QuestionAnalysis
from llm.llm_monitor import log_llm_call, TokenCountCallback
from utils.chat_utils import format_history
from service.prompt_manager import PromptManager

class SQLGenerator:

    def __init__(self, llm, prompt_manager: PromptManager):
        self.llm = llm
        self.pm = prompt_manager
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

    def generate(self, question: str, analysis: QuestionAnalysis, schema, nicknames: list[str] | None = None, error: str | None = None, few_shots: str = "", abbr_hints: str = "", auction_conditions: str = "", history: list[dict] | None = None):
        
        dynamic_prompts = self.pm.build_sql_rules(
            category=analysis.category,
            response_format=analysis.response_format
        )

        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.                                 

            {common_rules}

            {error_feedback}

            [SQL 생성 프로세스 - 반드시 이 순서로 추론해]
            1. 분석: 질문 의도 파악
            2. 테이블 선정: [스키마]와 [category_rules] 참조
            3. 로직 설계: JOIN, CTE, JSON 파싱 설계
            4. 검증: [공통 SQL 규칙] 준수 여부 체크
            5. 출력: 최종 SQL을 ```sql```태그 안에 작성
                                                  
            {response_format_rules}

            {category_rules}

            {few_shots}

            [용어 힌트]
            {abbr_hints}
            {term_rules}

            [이전 대화]
            {history}

            [질문]
            {question}

            [분석]
            {analysis}

            [SQL 생성 지시]
            위 분석 내용을 바탕으로 SQL을 작성하되, 특히 'JSON 파싱 문법'과 '최신 시점(MAX) 처리'에 집중해.

            [대상 닉네임]
            {nicknames}

            [스키마]
            {schema}

            {auction_option_hint}
        """)

        structured_llm = self.llm.with_structured_output(SQLWithUIType)
        chain = (prompt | structured_llm).with_retry(stop_after_attempt=2)

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
                    "analysis": analysis.dict() if hasattr(analysis, 'dict') else analysis,
                    "nicknames": ", ".join(nicknames) if nicknames else "없음",
                    "schema": schema,
                    "history": format_history(history, limit=4) if history else "없음",
                    "error_feedback": f"[이전 시도 오류]\n{error}" if error else "",
                    "few_shots": few_shots,
                    "abbr_hints": abbr_hints or "없음",
                    "term_rules": self._build_term_rules(abbr_hints) if abbr_hints else "",
                    "auction_option_hint": f"[경매장 옵션 조건]\n{auction_conditions}\n" if auction_conditions else "",

                    "common_rules": dynamic_prompts["common_rules"],
                    "response_format_rules": dynamic_prompts["response_format_rules"],
                    "category_rules": dynamic_prompts["category_rules"],
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

    def generate_validated(self, question: str, analysis: QuestionAnalysis, schema: dict, nicknames: list[str] | None = None, few_shots: str = "", all_tables: set | None = None, abbr_hints: str = "", auction_conditions: str = "", history: list[dict] | None = None) -> str:
        allowed = all_tables if all_tables is not None else set(schema.keys())

        def _check_invalid(sql: str) -> set:
            return {re.sub(r'\W', '', w.split(".")[-1]) for w in sql.split() if "lostark." in w} - allowed

        sql, _ = self.generate(question, analysis, schema, nicknames, few_shots=few_shots, abbr_hints=abbr_hints, auction_conditions=auction_conditions, history=history)
        invalid = _check_invalid(sql)
        if not invalid:
            return sql

        sql, _ = self.generate(question, analysis, schema, nicknames, few_shots=few_shots, abbr_hints=abbr_hints, auction_conditions=auction_conditions, history=history,
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
