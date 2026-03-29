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