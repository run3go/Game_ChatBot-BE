from langchain_core.documents import Document

# analysis_generator 프롬프트에 주입되는 은어 규칙
SLANG_RULES = """
- 보석 약어: [숫자]+[보석명 첫 글자]. 예) 9겁→9레벨 겁화의 보석, 7작→7레벨 작열의 보석, 10멸→10레벨 멸화의 보석
- 수집품 약어: 섬마→섬의 마음, 거심→거인의 심장, 오페별→오르페우스의 별
- 스킬 약어: 부파->부위 파괴. 트포->트라이포드, 전설 질풍의 룬 -> 전설 질풍
- 카드 약어: 세구빛->세상을 구하는 빛, 남바절->남겨진 바람의 절벽
""".strip()

GAME_KNOWLEDGE_DOCS = [

    Document(
        page_content=(
            "보석 약어 공식: [숫자]+[보석 이름 첫 글자]. "
            "예) 7멸=7레벨 멸화의 보석, 10겁=10레벨 겁화의 보석. "
            "보석 레벨·명칭을 조회할 때는 armory_gem_tb의 level, name 컬럼을 사용."
        ),
        metadata={"table": "armory_gem_tb"}
    ),
    Document(
        page_content=(
            "보석은 스킬에 장착되며, 어떤 스킬에 어떤 보석이 장착되었는지는 armory_gem_effects_tb를 통해 확인. "
            "'9겁을 장착한 스킬', '작열 보석이 달린 스킬' 등 보석 장착 스킬 조회 시 "
            "armory_gem_tb(보석 레벨·종류)와 armory_gem_effects_tb(적용 스킬명)를 JOIN해서 사용."
        ),
        metadata={"table": "armory_gem_tb"}
    ),
    Document(
        page_content=(
            "겁화·멸화는 피해 증가 보석, 작열·홍염은 재사용 대기시간 감소 보석. "
            "광휘의 보석은 옵션에 따라 겁화(피해 증가) 또는 작열(재사용 감소)로 부름. "
            "보석 종류·효과 조회: armory_gem_tb의 name, effect_type 컬럼."
        ),
        metadata={"table": "armory_gem_tb"}
    ),
    Document(
        page_content=(
            "캐릭터가 보유한 스킬 목록·스킬 정보 조회: armory_skills_tb 사용. "
            "스킬 이름·레벨·트라이포드·룬 정보가 저장됨. "
            "재사용 대기시간, 마나 소모량, 부위 파괴, 무력화, 카운터 정보가 저장됨. "
            "타입으로는 '일반','차지','콤보','홀딩','캐스팅','지점'이 있고, 공격타입으로는 '백 어택','헤드 어택'이 있음. "
            "파괴 스킬 조회 조건: WHERE weak_point >= 1. "
            "무력화 스킬 조회 조건: WHERE stagger IS NOT NULL."
        ),
        metadata={"table": "armory_skills_tb"}
    ),
    Document(
        page_content=(
            "수집품 약어: 섬마=섬의 마음, 거심=거인의 심장, 오페별=오르페우스의 별. "
            "수집품 개수·달성률 조회: armory_collectibles_tb의 type, point, max_point 컬럼."
        ),
        metadata={"table": "armory_collectibles_tb"}
    ),
]
