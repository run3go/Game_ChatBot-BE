import re
import time
from langchain_core.prompts import ChatPromptTemplate
from output_types import SQLWithUIType, QuestionAnalysis
from llm.llm_monitor import log_llm_call, TokenCountCallback
from llm.sql_rules import COMMON_RULES, RESPONSE_FORMAT_RULES, get_category_rules
from utils.chat_utils import format_history

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

    def generate(self, question: str, analysis: QuestionAnalysis, schema, nicknames: list[str] | None = None, error: str | None = None, few_shots: str = "", abbr_hints: str = "", auction_conditions: str = "", history: list[dict] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 DB 전문가야.

            {common_rules}

            {error_feedback}

            {response_format_rules}

            {category_rules}

            {few_shots}

            [용어 힌트 - 질문 속 표현과 DB 정식 명칭 매핑]
            {abbr_hints}

            {term_rules}

            [이전 대화 - 후속 질문 맥락 파악용]
            {history}
            ※ "다른", "나머지", "그 외" 같은 표현이 있으면 이전 대화에서 언급된 조건·분류를 제외하는 조건을 SQL에 반영해.

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

            {auction_option_hint}

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
                    "history": format_history(history, limit=4, max_ai_length=150) if history else "없음",
                    "error_feedback": f"[이전 시도 오류 - 반드시 수정]\n{error}\n위 오류를 반드시 수정해서 다시 생성해." if error else "",
                    "few_shots": few_shots,
                    "abbr_hints": abbr_hints or "없음",
                    "term_rules": self._build_term_rules(abbr_hints) if abbr_hints else "",
                    "auction_option_hint": (
                        f"[경매장 옵션 조건 - 최우선 적용]\n"
                        f"아래 조건을 WHERE절에 글자 하나도 바꾸지 말고 그대로 복사해서 포함해.\n"
                        f"{auction_conditions}\n"
                        f"⚠️ 위 조건 대신 다른 옵션명이나 수치를 임의로 사용하는 것은 절대 금지."
                    ) if auction_conditions else "",
                    "common_rules": COMMON_RULES,
                    "response_format_rules": RESPONSE_FORMAT_RULES,
                    "category_rules": get_category_rules(analysis.category),
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
