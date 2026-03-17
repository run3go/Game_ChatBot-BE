from sqlalchemy import text

NICKNAME_SET = set()

# DB에서 모든 닉네임 로드
def load_nicknames(db):
   
   global NICKNAME_SET
   
   rows = db.execute(text("""
        SELECT character_name
        FROM lostark.armory_profile_tb
   """))

   NICKNAME_SET = {r[0] for r in rows}

# 캐시에 존재하는 닉네임인지 확인
def is_cached_nickname(word):
   return word in NICKNAME_SET

# 닉네임 유효성 검사
def validate_nickname(db, word):
   
   if word in NICKNAME_SET:
      return True
   
   row = db.execute(text("""
    SELECT character_name
    FROM lostark.armory_profile_tb    
    WHERE character_name = :name
   """), {"name": word}).fetchone()

   if row:
      NICKNAME_SET.add(word)
      return True
   
   return False