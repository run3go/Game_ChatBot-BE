import json
from langchain_core.prompts import ChatPromptTemplate

class AnswerGenerator:

    def __init__(self, llm):
        self.llm = llm

    def answer_general(self, question: str, history: list[dict] | None = None):
        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            DB 조회 없이 게임 지식을 바탕으로 질문에 답해.
            답변은 간결하고 정확하게 마크다운 형식으로 작성해.
            이전 대화 맥락을 반드시 참고해서 답해.

            [이전 대화]
            {history}

            [질문]
            {question}
        """)
        history_text = ""
        if history:
            lines = [
                f"{'사용자' if m['role'] == 'user' else 'AI'}: {m['content']}"
                for m in history[-6:]
            ]
            history_text = "\n".join(lines)

        chain = prompt | self.llm
        for chunk in chain.stream({"question": question, "history": history_text or "없음"}):
            yield chunk.content

    def answer(self, question: str, data, history: list[dict] | None = None):
        data = [dict(row) for row in data]

        prompt = ChatPromptTemplate.from_template("""
            너는 로스트아크 AI 비서야.
            데이터를 기반으로 자연스럽게 설명해.

            [UI 적용 가이드]
            - 수치/능력치 비교: 반드시 표를 사용하고, 더 높은 값에 볼드체. 비교 수치가 하나일 때만 차잇값 표시. 표는 하나로 통합.
            - 아크 그리드: 👤 닉네임을 제목으로 쓰고 슬롯 분류/코어 이름/등급/포인트 표로 출력. 비교 시 캐릭터별 각각 작성.
            - 각인: 불렛 포인트로 나열 (어빌리티 스톤 0레벨 제외)
            - 아크 패시브: 두 캐릭터의 깨달음 1티어 효과명을 대조.
                - 같을 경우: 포인트/레벨 통합 표 + 진화/깨달음/도약 상세 효과 비교 표 출력. 다른 효과에 볼드체.
                - 다를 경우: 포인트/레벨 통합 표만 출력. 같은 값엔 볼드체 금지.
            - 이외 추가 분석 금지.

            [금지]
            - "판단", "비교한 결과", "효과가 달라서", "~만 비교했습니다" 사용 금지
            - 분석 과정/필터링 기준 설명 금지
            - 처음부터 해당 데이터만 존재했던 것처럼 담백하게 출력
            - 응답을 코드블록(```)으로 감싸지 마. 마크다운을 직접 출력.

            [답변 예시]

                | 항목 | 첫번째도구 | 황로드유 |
                | :--- | :---: | :---: |
                | 공격력 | 35 | **52** |
                | 추가 피해 | 26 | **57** |
                | 낙인력 | **32** | 22 |

                👤 황로드유
                | 슬롯 분류 | 코어 이름 | 등급 | 포인트 |
                | :--- | :--- | :---: | :---: |
                | 질서의 해 | 코어 : 전술 제어 | 유물 | 18 |
                | 질서의 달 | 코어 : 방어 전술 | 유물 | 19 |

                | 캐릭터 | 첫번째도구 | 황로드유 | 차잇값 |
                | :--- | :---: | :---: | :---: |
                | 전투력 | 4600.57 | 4450.00 | 150.57 |

                - 첫번째도구
                    - 각성 (2레벨)
                    - 전문의 (4레벨)
                - 쁘허
                    - 각성 (4레벨)
                    - 전문의 (4레벨)

                | 구분 | 캐릭터 | 진화 (P/Lv) | 깨달음 (P/Lv) | 도약 (P/Lv) |
                | :--- | :--- | :---: | :---: | :---: |
                | **포인트/레벨** | 첫번째도구 | 140 / **6랭크 26Lv** | 101 / 6랭크 26Lv | **72** / 5랭크 18Lv |
                | | 황로드유 | 140 / 6랭크 25Lv | 101 / **6랭크 28Lv** | 70 / **6랭크 25Lv** |

                #### 1. 진화
                | 티어 | 첫번째도구 | 쁘허 |
                | :---: | :--- | :--- |
                | **1티어** | • 신속 (26Lv) | • 신속 (26Lv) |
                | **5티어** | • **입식 타격가 (2Lv)** | • **마나 용광로 (2Lv)** |

            [이전 대화]
            {history}

            [질문]
            {question}

            [데이터(JSON)]
            {data}
        """)

        history_text = ""
        if history:
            lines = [
                f"{'사용자' if m['role'] == 'user' else 'AI'}: {m['content']}"
                for m in history[-6:]
            ]
            history_text = "\n".join(lines)

        chain = prompt | self.llm

        for chunk in chain.stream({
            "question": question,
            "data": json.dumps(data, ensure_ascii=False, default=float),
            "history": history_text or "없음"
        }):
            yield chunk.content
