from sqlalchemy import text

NICKNAME_SET = set()

def load_nicknames(db):
   global NICKNAME_SET
   rows = db.execute(text("""
        SELECT character_name
        FROM lostark.armory_profile_tb
   """))
   NICKNAME_SET = {r[0] for r in rows}
   return len(NICKNAME_SET)

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

def validate_nicknames_batch(db, names: list[str]) -> tuple[list[str], list[str]]:
    """names를 한 번의 DB 쿼리로 검증. (verified, unverified) 반환"""
    verified_set = {n for n in names if n in NICKNAME_SET}
    unchecked = [n for n in names if n not in NICKNAME_SET]

    if unchecked:
        rows = db.execute(text("""
            SELECT character_name
            FROM lostark.armory_profile_tb
            WHERE character_name = ANY(:names)
        """), {"names": unchecked}).fetchall()
        found = {r[0] for r in rows}
        NICKNAME_SET.update(found)
        verified_set.update(found)

    verified = [n for n in names if n in verified_set]
    unverified = [n for n in names if n not in verified_set]
    return verified, unverified